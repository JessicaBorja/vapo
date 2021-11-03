from datetime import datetime
import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import itertools
import logging
import gym

from vapo.sac_agent.sac_utils.replay_buffer import ReplayBuffer
from vapo.sac_agent.sac_utils.utils import tt, soft_update, get_nets


class SAC():
    def __init__(self, env, eval_env=None, save_dir="./trained_models",
                 gamma=0.99, alpha="auto",
                 actor_lr=3e-4, critic_lr=3e-4, alpha_lr=3e-4,
                 tau=0.005, learning_starts=1000,
                 batch_size=256, buffer_size=1e6,
                 model_name="sac", net_cfg=None, log=None,
                 save_replay_buffer=False, init_temp=0.01):
        self._save_replay_buffer = save_replay_buffer
        self.log = log
        if(not log):
            self.log = logging.getLogger(__name__)
        self.save_dir = save_dir
        self.env = env
        self.eval_env = eval_env
        self._log_by_episodes = False
        if(eval_env is None):
            self._log_by_episodes = True
            self.eval_env = env

        # Replay buffer
        _cnn_policy_cond = ["gripper_depth_obs", "gripper_img_obs",
                            "static_depth_obs", "static_img_obs"]
        _img_obs = False
        obs_space = env.observation_space
        if(isinstance(obs_space, gym.spaces.Dict) and
           any([x in _cnn_policy_cond for x in obs_space])):
            _img_obs = True
        print("SAC: images as observation: %s" % _img_obs)
        self._max_size = buffer_size
        self._replay_buffer = ReplayBuffer(buffer_size, _img_obs, self.log)
        self.batch_size = batch_size

        # Agent
        self._gamma = gamma
        self.tau = tau

        # networks
        self._auto_entropy = False
        if isinstance(alpha, str):  # auto
            self._auto_entropy = True
            self.ent_coef = 1  # entropy coeficient
            # heuristic value
            self.target_entropy = -np.prod(env.action_space.shape).item()
            self.log_ent_coef = torch.tensor(np.log(init_temp),
                                             requires_grad=True,
                                             device="cuda")  # init value
            self.ent_coef_optimizer = optim.Adam([self.log_ent_coef],
                                                 lr=alpha_lr)
        else:
            self.ent_coef = alpha  # entropy coeficient

        self.learning_starts = learning_starts

        policy_net, critic_net, obs_space, action_dim = \
            get_nets(_img_obs, obs_space, env.action_space, self.log)
        self._pi = policy_net(obs_space, action_dim,
                              action_space=env.action_space,
                              **net_cfg).cuda()
        self._q1 = critic_net(obs_space, action_dim, **net_cfg).cuda()
        self._q1_target = critic_net(obs_space, action_dim, **net_cfg).cuda()
        self._q2 = critic_net(obs_space, action_dim, **net_cfg).cuda()
        self._q2_target = critic_net(obs_space, action_dim, **net_cfg).cuda()

        self._pi_optim = optim.Adam(self._pi.parameters(), lr=actor_lr)

        self._q1_target.load_state_dict(self._q1.state_dict())
        self._q1_optimizer = optim.Adam(self._q1.parameters(), lr=critic_lr)

        self._q2_target.load_state_dict(self._q2.state_dict())
        self._q2_optimizer = optim.Adam(self._q2.parameters(), lr=critic_lr)

        _q_params = itertools.chain(
                        self._q1.parameters(),
                        self._q2.parameters())
        self._q_optim = optim.Adam(_q_params, lr=critic_lr)
        self._loss_function = nn.MSELoss()
        # Summary Writer
        if not os.path.exists("./results"):
            os.makedirs("./results")
        # models folder
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        self.model_name = "{}_{}".format(
                                    model_name,
                                    datetime.now().strftime('%d-%m_%H-%M'))
        self.writer_name = "./results/{}".format(self.model_name)
        # self.eval_writer_name = "./results/%s_eval"%self.model_name
        self.trained_path = "{}/{}".format(self.save_dir, self.model_name)

    # update alpha(entropy coeficient)
    def _update_entropy(self, log_probs):
        if(self._auto_entropy):
            self.ent_coef_optimizer.zero_grad()
            ent_coef_loss = -(self.log_ent_coef *
                              (log_probs +
                               self.target_entropy).detach()).mean()
            ent_coef_loss.backward()
            self.ent_coef_optimizer.step()
            self.ent_coef = self.log_ent_coef.exp()
            return ent_coef_loss.item()
        else:
            return 0

    # Update all networks
    def _update(self, td_target, batch_states, batch_actions):
        plot_data = {}
        # Critic 1
        curr_prediction_c1 = self._q1(batch_states, batch_actions)
        loss_c1 = self._loss_function(curr_prediction_c1, td_target.detach())

        # Critic 2
        curr_prediction_c2 = self._q2(batch_states, batch_actions)
        loss_c2 = self._loss_function(curr_prediction_c2, td_target.detach())
        # --- update two critics w/same optimizer ---#
        self._q_optim.zero_grad()
        loss_critics = loss_c1 + loss_c2
        loss_critics.backward()
        self._q_optim.step()

        plot_data["critic_loss"] = [loss_c1.item(), loss_c2.item()]
        # ---------------- Policy network update -------------#
        predicted_actions, log_probs = self._pi.act(batch_states,
                                                    deterministic=False,
                                                    reparametrize=True)
        critic_value = torch.min(
            self._q1(batch_states, predicted_actions),
            self._q2(batch_states, predicted_actions))
        # Actor update/ gradient ascent
        self._pi_optim.zero_grad()
        policy_loss = (self.ent_coef * log_probs - critic_value).mean()
        policy_loss.backward()
        self._pi_optim.step()
        plot_data["actor_loss"] = policy_loss.item()

        # ---------------- Entropy network update -------------#
        ent_coef_loss = self._update_entropy(log_probs)
        plot_data["ent_coef"] = self.ent_coef
        plot_data["ent_coef_loss"] = ent_coef_loss

        # ------------------ Target Networks update -------------------#
        soft_update(self._q1_target, self._q1, self.tau)
        soft_update(self._q2_target, self._q2, self.tau)

        return plot_data

    # One single training timestep
    # Take one step in the environment and update the networks
    def training_step(self, s, ts, ep_return, ep_length, plot_data):
        # sample action and scale it to action space
        a, _ = self._pi.act(tt(s), deterministic=False)
        a = a.cpu().detach().numpy()
        ns, r, done, info = self.env.step(a)

        # check if it actually earned the reward
        success = False
        if(r >= 200 and self.env.task == "pickup"):
            self.move_to_box(self.env)
            # We don't know which obj aff model chose,
            # so give success if any in box
            success = self.eval_grasp_success(self.env, any=True)
            # If lifted incorrectly get no reward
            if(not success):
                r = 0
        elif(self.env.task != "pickup" and r > 0):
            success = True

        self._replay_buffer.add_transition(s, a, r, ns, done)
        s = ns
        ep_return += r
        ep_length += 1

        # Replay buffer has enough data
        if(self._replay_buffer.__len__() >= self.batch_size
           and not done and ts > self.learning_starts):

            sample = self._replay_buffer.sample(self.batch_size)
            batch_states, batch_actions, batch_rewards,\
                batch_next_states, batch_terminal_flags = sample

            with torch.no_grad():
                next_actions, log_probs = self._pi.act(
                                                batch_next_states,
                                                deterministic=False,
                                                reparametrize=False)

                target_qvalue = torch.min(
                    self._q1_target(batch_next_states, next_actions),
                    self._q2_target(batch_next_states, next_actions))

                td_target = \
                    batch_rewards \
                    + (1 - batch_terminal_flags) * self._gamma * \
                    (target_qvalue - self.ent_coef * log_probs)

            # ----------------  Networks update -------------#
            new_data = self._update(td_target,
                                    batch_states,
                                    batch_actions)
            for k, v in plot_data.items():
                v.append(new_data[k])
        return s, done, success, ep_return, ep_length, plot_data, info

    def _on_train_ep_end(self, writer, ts, episode, total_ts,
                         best_return, episode_length, episode_return, success):
        self.log.info(
            "Episode %d: %d Steps," % (episode, episode_length) +
            "Success: %s " % str(success) +
            "Return: %.3f, total timesteps: %d/%d" %
            (episode_return, ts, total_ts))

        # Summary Writer
        # log everything on timesteps to get the same scale
        writer.add_scalar('train/success',
                          success, ts)
        writer.add_scalar('train/episode_return',
                          episode_return, ts)
        writer.add_scalar('train/episode_length',
                          episode_length, ts)

        if(episode_return >= best_return):
            self.log.info("[%d] New best train ep. return!%.3f" %
                          (episode, episode_return))
            self.save(self.trained_path + "_best_train.pth")
            best_return = episode_return

        # Always save last model(last training episode)
        self.save(self.trained_path + "_last.pth")
        return best_return

    # Evaluate model and log plot_data to writter
    # Returns: Reseted plot_data and newest best_eval_reward
    def _eval_and_log(self, writer, t, episode, plot_data, most_tasks,
                      best_eval_return, n_eval_ep, max_ep_length,
                      eval_all_objs=False):
        # If all objs are already on the table
        if(eval_all_objs
           and self.eval_env.rand_positions is None):
            return
        # Log plot_data to writer
        for key, value in plot_data.items():
            if value:  # not empty
                if(key == "critic_loss"):
                    data = np.mean(value[-1])
                else:
                    data = value[-1]  # np.mean(value)
                writer.add_scalar("train/%s" % key, data, t)

        # Reset plot_data
        plot_data = {"actor_loss": [],
                     "critic_loss": [],
                     "ent_coef_loss": [], "ent_coef": []}

        # Evaluate agent for n_eval_ep with max_ep_length
        if(self.eval_env.task == "pickup"):
            n_eval_ep = len(self.eval_env.scene.table_objs)

        if(eval_all_objs):
            self.log.info("Running full objs validation...")
            success_lst, success_objs = \
                self.eval_all_objs(self.eval_env, max_ep_length)
            self.log.info("End full objs validation...")
        else:
            mean_return, mean_length, success_lst, success_objs = \
                self.evaluate(self.eval_env, max_ep_length,
                              n_episodes=n_eval_ep)
            writer.add_scalar('eval/mean_return(%dep)' %
                              (n_eval_ep), mean_return, t)
            writer.add_scalar('eval/mean_ep_length(%dep)' %
                              (n_eval_ep), mean_length, t)
            # Log results to writer
            if(mean_return >= best_eval_return):
                self.log.info("[%d] New best eval avg. return!%.3f" %
                              (episode, mean_return))
                self.save(self.trained_path+"_best_eval.pth")
                best_eval_return = mean_return
                # Meassure success
        n_success = np.sum(success_lst)
        if(n_success >= most_tasks):
            self.log.info("[%d] New most successful! %d/%d" %
                          (episode, n_success, len(success_lst)))
            self.save(self.trained_path
                      + "_most_tasks_from_%d.pth" % len(success_lst))
            most_tasks = n_success

        writer.add_scalar('eval/success(%dep)' %
                          (len(success_lst)), n_success, t)

        # If environment definition allows for randoming environment
        # Change scene when method already does something
        if(self.eval_env.task == "pickup"
           and self.eval_env.rand_positions
           and not eval_all_objs
           and n_success >= 2):
            for obj in success_objs:
                obj_class = self.eval_env.class_per_obj[obj]
                self.p_dist[obj_class] += 1
            self.eval_env.load_rand_scene(success_objs)
        return best_eval_return, most_tasks, plot_data

    def eval_all_objs(self):
        raise NotImplementedError

    def save(self, path):
        save_dict = {
            'actor_dict': self._pi.state_dict(),
            'actor_optimizer_dict': self._pi_optim.state_dict(),

            'critic_1_dict': self._q1.state_dict(),
            'critic_1_target_dict': self._q1_target.state_dict(),
            'critic_1_optimizer_dict': self._q1_optimizer.state_dict(),

            'critic_2_dict': self._q2.state_dict(),
            'critic_2_target_dict': self._q2_target.state_dict(),
            'critic_2_optimizer_dict': self._q2_optimizer.state_dict(),
            'critics_optim': self._q_optim.state_dict(),

            'ent_coef': self.ent_coef}
        if self._auto_entropy:
            save_dict['ent_coef_optimizer'] = \
                 self.ent_coef_optimizer.state_dict()
        if self._save_replay_buffer:
            self._replay_buffer.save(os.path.join(self.save_dir,
                                     "replay_buffer"))
        torch.save(save_dict, path)

    def load(self, path):
        if os.path.isfile(path):
            print("Loading checkpoint")
            checkpoint = torch.load(path)

            self._pi.load_state_dict(checkpoint['actor_dict'])
            self._pi_optim.load_state_dict(checkpoint['actor_optimizer_dict'])

            self._q1.load_state_dict(checkpoint['critic_1_dict'])
            self._q1_target.load_state_dict(checkpoint['critic_1_target_dict'])
            self._q1_optimizer.load_state_dict(
                checkpoint['critic_1_optimizer_dict'])

            self._q2.load_state_dict(checkpoint['critic_2_dict'])
            self._q2_target.load_state_dict(checkpoint['critic_2_target_dict'])
            self._q2_optimizer.load_state_dict(
                checkpoint['critic_2_optimizer_dict'])

            self.ent_coef = checkpoint["ent_coef"]
            self.ent_coef_optimizer.load_state_dict(checkpoint['ent_coef_optimizer'])

            replay_buffer_dir = os.path.join(os.path.dirname(path),
                                             "replay_buffer")
            if(os.path.isdir(replay_buffer_dir)):
                self._replay_buffer.load(replay_buffer_dir)
            print("load done")
            return True
        else:
            raise TypeError("Cannot find path " + path)
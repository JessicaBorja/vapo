import os
import logging
import torch
import numpy as np
import cv2
import pybullet as p

import gym
from gym import spaces

from vapo.utils.img_utils import torch_to_numpy, viz_aff_centers_preds
from vapo.env_wrappers.utils import get_obs_space, get_transforms_and_shape, \
                                    find_cam_ids, init_aff_net, \
                                    depth_preprocessing, img_preprocessing
logger = logging.getLogger(__name__)


class AffordanceWrapper(gym.Wrapper):
    def __init__(self, EnvClass, env_cfg, max_ts, img_size,
                 gripper_cam, static_cam, transforms=None,
                 use_pos=False, use_aff_termination=False,
                 affordance_cfg=None, target_search="env",
                 max_target_dist=0.15, use_env_state=False,
                 train=False, save_images=False, viz=False,
                 history_length=None, skip_frames=None):
        env_cfg.seed = None
        self.env = EnvClass(**env_cfg)
        self.env.target_radius = max_target_dist

        super(AffordanceWrapper, self).__init__(self.env)
        self.task = self.env.task
        self.target_radius = self.env.target_radius

        # TERMINATION
        # or target_search == "affordance"
        self.use_aff_termination = use_aff_termination

        # REWARD FUNCTION
        self.affordance_cfg = affordance_cfg
        self.cam_ids = find_cam_ids(self.env.cameras)
        self.ts_counter = 0
        self.max_ts = max_ts
        if(self.affordance_cfg.gripper_cam.densify_reward):
            print("RewardWrapper: Gripper cam to shape reward")

        # OBSERVATION
        self.img_size = img_size
        shape = (1, img_size, img_size)

        # Prepreocessing for affordance model
        _transforms_cfg = affordance_cfg.transforms["validation"]
        _static_aff_im_size = 200
        if(img_size in affordance_cfg.static_cam):
            _static_aff_im_size = affordance_cfg.static_cam.img_size
        self.aff_transforms = {
            "static": get_transforms_and_shape(_transforms_cfg,
                                               self.img_size,
                                               out_size=_static_aff_im_size)[0],
            "gripper": get_transforms_and_shape(_transforms_cfg,
                                                self.img_size)[0]}

        # Preprocessing for RL policy obs
        _transforms_cfg =\
            transforms["train"] if train else transforms["validation"]
        self.rl_transforms, shape = get_transforms_and_shape(_transforms_cfg,
                                                             self.img_size)
        self.channels = shape[0]

        # Cameras defaults
        self.obs_it = 0
        self.save_images = save_images
        self.viz = viz

        # Parameters to define observation
        self.gripper_cam_cfg = gripper_cam
        self.static_cam_cfg = static_cam
        self.use_robot_obs = use_pos
        self.use_env_state = use_env_state
        # self._mask_transforms = DistanceTransform()

        # Parameters to store affordance
        self.gripper_cam_aff_net, affordance_cfg = \
            init_aff_net(affordance_cfg, 'gripper')
        self.static_cam_aff_net, affordance_cfg = \
            init_aff_net(affordance_cfg, 'static')
        self.curr_raw_obs = None

        # Observation and action space
        if(self.env.task == "pickup"):
            # 0-2 -> position , 3 -> yaw angle 4 gripper action
            _action_space = np.ones(5)
        else:
            # 0-2 -> position , 3-5 -> orientation, 6 gripper action
            _action_space = np.ones(7)
        self.action_space = spaces.Box(_action_space * -1, _action_space)
        self.observation_space = get_obs_space(affordance_cfg,
                                               self.gripper_cam_cfg,
                                               self.static_cam_cfg,
                                               self.channels, self.img_size,
                                               self.use_robot_obs,
                                               self.task,
                                               oracle=self.use_env_state)

        # Save images
        self.gripper_cam_imgs = {}

    def reset(self, **kwargs):
        observation = self.env.reset(**kwargs)
        return self.observation(observation)

    def step(self, action):
        observation, reward, done, info = self.env.step(action)
        return self.observation(observation), self.reward(reward), \
            self.termination(done, observation), info

    def observation(self, obs):
        # "rgb_obs", "depth_obs", "robot_obs","scene_obs"
        self.curr_raw_obs = obs
        obs = {}
        obs_dict = self.curr_raw_obs.copy()
        gripper_obs, gripper_dict = \
            self.get_cam_obs(obs_dict, "gripper",
                             self.gripper_cam_aff_net,
                             self.gripper_cam_cfg,
                             self.affordance_cfg.gripper_cam,
                             self.cam_ids["gripper"])
        static_obs, static_dict = \
            self.get_cam_obs(obs_dict, "static",
                             self.static_cam_aff_net,
                             self.static_cam_cfg,
                             self.affordance_cfg.static_cam,
                             self.cam_ids["static"])
        obs = {**gripper_obs, **static_obs}
        viz_dict = {**gripper_dict, **static_dict}
        if(self.use_robot_obs):
            if(self.task == "pickup"):
                # *tcp_pos(3), *tcp_euler(1) z angle ,
                # gripper_opening_width(1), gripper_action
                obs["robot_obs"] = np.array([*obs_dict["robot_obs"][:3],
                                            *obs_dict["robot_obs"][5:7],
                                            obs_dict["robot_obs"][-1]])
            else:
                # *tcp_pos(3), *tcp_euler(3),
                # gripper_opening_width(1), gripper_action
                obs["robot_obs"] = np.array([*obs_dict["robot_obs"][:7],
                                             obs_dict["robot_obs"][-1]])
                if(self.use_env_state):
                    obs["robot_obs"] = np.append(obs["robot_obs"],
                                                 self.env.get_target_pos()[-1])
        self.obs_it += 1
        if(self.viz):
            for cam_name, cam_id in self.cam_ids.items():
                cv2.imshow("%s_cam" % cam_name,
                           self.curr_raw_obs['rgb_obs'][cam_id][:, :, ::-1])
            cv2.waitKey(1)
        if(self.save_images):
            for cam_name, cam_id in self.cam_ids.items():
                os.makedirs('./images/%s_orig' % cam_name, exist_ok=True)
                cv2.imwrite("./images/%s_orig/img_%04d.png"
                            % (cam_name, self.obs_it),
                            self.curr_raw_obs['rgb_obs'][cam_id][:, :, ::-1])
            for img_path, img in viz_dict.items():
                folder = os.path.dirname(img_path)
                os.makedirs(folder, exist_ok=True)
                cv2.imwrite(img_path, img)
        return obs

    def reward(self, rew):
        # modify rew
        if(self.affordance_cfg.gripper_cam.densify_reward):
            # set by observation wrapper so that
            # both have the same observation on
            # a given timestep
            if(self.curr_raw_obs is not None):
                obs_dict = self.curr_raw_obs
            else:
                obs_dict = self.get_obs()
            tcp_pos = obs_dict["robot_obs"][:3]

            # Create positive reward relative to the distance
            # between the closest point detected by the affordances
            # and the end effector position
            # p.removeAllUserDebugItems()
            # p.addUserDebugText("aff_target",
            #                    textPosition=self.env.unwrapped.current_target,
            #                    textColorRGB=[0, 1, 0])

            # If episode is not done because of moving to far away
            if(not self.termination(self.env._termination(), obs_dict)
               and self.ts_counter < self.max_ts - 1):
                distance = np.linalg.norm(
                        tcp_pos - self.env.unwrapped.current_target)
                # cannot be larger than 1
                # scale dist increases as it falls away from object
                scale_dist = min(distance / self.target_radius, 1)
                if(self.task == "pickup"):
                    rew += (1 - scale_dist)**0.4
                elif(self.task == "slide"):
                    # goal_pose = np.array([0.25, 0.75, 0.74])
                    # dist_to_goal = np.linalg.norm(
                    #   self.env.unwrapped.current_target - goal_pose)
                    # # max posible distance clip
                    # dist_to_goal = 1 - min(dist_to_goal/0.6, 1)
                    scale_dist = 1 - scale_dist
                    rew += scale_dist
                elif(self.task == "drawer"):
                    # goal_pose = np.array([-0.05, 0.30, 0.42])
                    # dist_to_goal = np.linalg.norm(
                    #   self.env.unwrapped.current_target - goal_pose)
                    # # max posible distance clip
                    # dist_to_goal = 1 - min(dist_to_goal/0.25, 1)
                    scale_dist = 1 - scale_dist
                    rew += scale_dist
                else:
                    rew = 1 - scale_dist
                self.ts_counter += 1
            else:
                # If episode was successful
                if(rew > 0):
                    # Reward for remaining ts
                    rew += self.max_ts - 1 - self.ts_counter
                self.ts_counter = 0
        return rew

    def termination(self, done, obs):
        # If distance between detected target and robot pos
        #  deviates more than target_radius
        # p.removeAllUserDebugItems()
        p.addUserDebugText("i",
                           textPosition=self.current_target,
                           textColorRGB=[0, 0, 1])
        done = self.env._termination()
        if(self.use_aff_termination):
            distance = np.linalg.norm(self.env.unwrapped.current_target
                                      - obs["robot_obs"][:3])
        else:
            # Real distance
            target_pos, _ = self.env.get_target_pos()
            p.addUserDebugText("t",
                    textPosition=target_pos,
                    textColorRGB=[0, 1, 0])
            distance = np.linalg.norm(target_pos
                                      - obs["robot_obs"][:3])
        return done or distance > self.target_radius

    def get_cam_obs(self, obs_dict, cam_type, aff_net,
                    obs_cfg, aff_cfg, cam_id):
        obs, viz_dict = {}, {}
        if(obs_cfg.use_depth):
            # Resize
            depth_obs = depth_preprocessing(
                            obs_dict['depth_obs'][cam_id],
                            self.img_size)
            obs["%s_depth_obs" % cam_type] = depth_obs
        if(obs_cfg.use_img):
            # Transform rgb to grayscale
            img_obs = img_preprocessing(
                                obs_dict['rgb_obs'][cam_id],
                                self.rl_transforms)
            # 1, W, H
            obs["%s_img_obs" % cam_type] = img_obs

        get_gripper_target = cam_type == "gripper" and (
                    self.affordance_cfg.gripper_cam.densify_reward
                    or self.affordance_cfg.gripper_cam.target_in_obs
                    or self.affordance_cfg.gripper_cam.use_distance)

        if(aff_net is not None and (aff_cfg.use or get_gripper_target)):
            # Np array 1, H, W
            processed_obs = img_preprocessing(
                                obs_dict['rgb_obs'][cam_id],
                                self.aff_transforms[cam_type])
            with torch.no_grad():
                # 1, 1, H, W in range [-1, 1]
                obs_t = torch.tensor(processed_obs).unsqueeze(0)
                obs_t = obs_t.float().cuda()

                # 1, H, W
                # aff_logits, aff_probs, aff_mask, directions
                _, aff_probs, aff_mask, directions = aff_net(obs_t)
                # aff_mask = self._mask_transforms(aff_mask).cuda()
                # foreground/affordance Mask
                mask = torch_to_numpy(aff_mask)
                if(obs_cfg.use_img and aff_mask.shape[1:] != img_obs.shape[1:]):
                    new_shape = (aff_mask.shape[0], *img_obs.shape[1:])
                    mask = np.resize(mask, new_shape)
                if(get_gripper_target):
                    preds = {"%s_aff" % cam_type: aff_mask,
                             "%s_center_dir" % cam_type: directions,
                             "%s_aff_probs" % cam_type: aff_probs}

                    # Computes newest target
                    gripper_cam_id = self.cam_ids["gripper"]
                    viz_dict = \
                        self.find_target_center(gripper_cam_id,
                                                obs_dict['rgb_obs'][gripper_cam_id],
                                                obs_dict['depth_obs'][gripper_cam_id],
                                                obs_dict["robot_obs"][6],
                                                preds)
            if(self.affordance_cfg.gripper_cam.target_in_obs):
                obs["detected_target_pos"] = self.env.unwrapped.current_target
            if(self.affordance_cfg.gripper_cam.use_distance):
                distance = np.linalg.norm(self.env.unwrapped.current_target
                                          - obs_dict["robot_obs"][:3])
                obs["target_distance"] = np.array([distance])
            if(aff_cfg.use):
                # m = np.transpose(mask * 255,(1, 2, 0)).astype('uint8')
                # cv2.imshow("%s_aff" % cam_type, m)
                obs["%s_aff" % cam_type] = mask
            # if(self.viz):
            #     cv2.imshow("static_obs", obs_dict['rgb_obs'][-1][:, :, ::-1])
        return obs, viz_dict

    # Aff-center
    def find_target_center(self, cam_id, orig_img, depth, gripper_width, obs):
        """
        Args:
            orig_img: np array, RGB original resolution from camera
                        shape = (1, cam.height, cam.width)
                        range = 0 to 255
                        Only used for vizualization purposes
            obs: dictionary
                - "img_obs":
                - "gripper_aff":
                    affordance segmentation mask, range 0-1
                    np.array(size=(1, img_size,img_size))
                - "gripper_aff_probs":
                    affordance activation function output
                    np.array(size=(1, n_classes, img_size,img_size))
                    range 0-1
                - "gripper_center_dir": center direction predictions
                    vectors in pixel space
                    np.array(size=(1, 2, img_size,img_size))
                np array, int64
                    shape = (1, img_size, img_size)
                    range = 0 to 1
        return:
            centers: list of 3d points (x, y, z)
        """
        aff_mask = obs["gripper_aff"]
        aff_probs = obs["gripper_aff_probs"]
        directions = obs["gripper_center_dir"]
        cam = self.cameras[cam_id]
        im_dict = {}
        # Predict affordances and centers
        aff_mask, center_dir, object_centers, object_masks = \
            self.gripper_cam_aff_net.predict(aff_mask, directions)

        # Visualize predictions
        if(self.viz or self.save_images):
            depth_img = cv2.resize(depth, orig_img.shape[:2])
            cv2.imshow("depth", depth_img)
            if(self.save_images):
                # Now between 0 and 8674
                write_depth = depth_img - depth_img.min()
                write_depth = write_depth / write_depth.max() * 255
                os.makedirs("./images/gripper_depth", exist_ok=True)
                cv2.imwrite("./images/gripper_depth/img_%04d.png"
                            % self.obs_it,
                            np.uint8(write_depth))
            im_dict = viz_aff_centers_preds(orig_img, aff_mask, aff_probs,
                                            center_dir, object_centers,
                                            object_masks,
                                            "gripper",
                                            self.obs_it,
                                            save_images=self.save_images)

        # Plot different objects
        cluster_outputs = []
        object_centers = [torch_to_numpy(o) for o in object_centers]
        if(len(object_centers) <= 0):
            return im_dict

        # To numpy
        aff_probs = torch_to_numpy(aff_probs)
        aff_probs = np.transpose(aff_probs[0], (1, 2, 0))  # H, W, 2
        object_masks = torch_to_numpy(object_masks[0])  # H, W

        obj_class = np.unique(object_masks)[1:]
        obj_class = obj_class[obj_class != 0]  # remove background class

        # Look for most likely center
        n_pixels = aff_mask.shape[1] * aff_mask.shape[2]
        pred_shape = aff_probs.shape[:2]
        orig_shape = depth.shape[:2]
        for i, o in enumerate(object_centers):
            # Mean prob of being class 1 (foreground)
            cluster = aff_probs[object_masks == obj_class[i], 1]
            robustness = np.mean(cluster)
            pixel_count = cluster.shape[0] / n_pixels

            # Convert back to observation size
            o = (o * orig_shape / pred_shape).astype("int64")
            if(self.env.task == "drawer" or self.env.task == "slide"):
                # As center might  not be exactly in handle
                # look for max depth around neighborhood
                n = 10
                uv_max = np.clip(o + [n, n], 0, orig_shape)
                uv_min = np.clip(o - [n, n], 0, orig_shape)
                depth_window = depth[uv_min[0]:uv_max[0], uv_min[1]:uv_max[1]]
                proposal = np.argwhere(depth_window == np.min(depth_window))[0]
                v = o[0] - n + proposal[0]
                u = o[1] - n + proposal[1]
            else:
                v, u = o
            world_pt = cam.deproject([u, v], depth)
            c_out = {"center": world_pt,
                     "pixel_count": pixel_count,
                     "robustness": robustness}
            cluster_outputs.append(c_out)
            # if(robustness > max_robustness):
            #     max_robustness = robustness
            #     target_px = o
            #     target_world = world_pt

        # p.removeAllUserDebugItems()

        # self.env.unwrapped.current_target = target_world
        # Maximum distance given the task
        most_robust = 0
        for out_dict in cluster_outputs:
            c = out_dict["center"]
            # If aff detects closer target which is large enough
            # and Detected affordance close to target
            dist = np.linalg.norm(self.env.unwrapped.current_target - c)
            if(dist < self.target_radius/2):
                if(out_dict["robustness"] > most_robust):
                    self.env.unwrapped.current_target = c
                    most_robust = out_dict["robustness"]

        # See selected point
        # p.addUserDebugText("target",
        #                    textPosition=self.env.unwrapped.current_target,
        #                    textColorRGB=[1, 0, 0])
        return im_dict

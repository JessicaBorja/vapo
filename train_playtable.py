import hydra
import logging

from vr_env.envs.play_table_env import PlayTableSimEnv
from env_wrappers.env_wrapper import RLWrapper
from env_wrappers.utils import get_name
from combined.combined import Combined
from sac_agent.sac_utils.utils import set_init_pos


@hydra.main(config_path="./config", config_name="cfg_playtable")
def main(cfg):
    if(cfg.init_angle):
        init_pos = cfg.env.robot_cfg.initial_joint_positions
        init_pos = set_init_pos(cfg.task, init_pos) 
        cfg.env.robot_cfg.initial_joint_positions = init_pos

    # Auto generate names given dense, aff-mask, aff-target
    log = logging.getLogger(__name__)
    cfg.model_name = get_name(cfg, cfg.model_name)
    max_ts = cfg.agent.learn_config.max_episode_length
    for i in range(cfg.repeat_training):
        training_env = RLWrapper(PlayTableSimEnv, cfg.env, max_ts,
                                 train=True,
                                 affordance_cfg=cfg.affordance,
                                 viz=cfg.viz_obs,
                                 **cfg.env_wrapper)

        sac_cfg = {"env": training_env,
                   "eval_env": None,
                   "model_name": cfg.model_name,
                   "save_dir": cfg.agent.save_dir,
                   "net_cfg": cfg.agent.net_cfg,
                   "log": log,
                   **cfg.agent.hyperparameters}

        log.info("model: %s" % cfg.model_name)
        model = Combined(cfg,
                         sac_cfg=sac_cfg,
                         target_search_mode=cfg.target_search)
        model.learn(**cfg.agent.learn_config)
        training_env.close()
        # eval_env.close()


if __name__ == "__main__":
    main()

import hydra
import logging

from vapo.env_wrappers.play_table_rl import PlayTableRL
from vapo.env_wrappers.aff_wrapper import AffordanceWrapper
from vapo.env_wrappers.utils import get_name
from vapo.combined.combined import Combined


@hydra.main(config_path="../config", config_name="cfg_tabletop")
def main(cfg):
    # Auto generate names given dense, aff-mask, aff-target
    log = logging.getLogger(__name__)
    cfg.model_name = get_name(cfg, cfg.model_name)
    max_ts = cfg.agent.learn_config.max_episode_length
    for i in range(cfg.repeat_training):
        training_env = AffordanceWrapper(
                                 PlayTableRL, cfg.env, max_ts,
                                 train=True,
                                 affordance_cfg=cfg.affordance,
                                 target_search=cfg.target_search,
                                 viz=cfg.viz_obs,
                                 save_images=cfg.save_images,
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
                         target_search_mode=cfg.target_search,
                         rand_target=True)
        model.learn(**cfg.agent.learn_config)
        training_env.close()
        # eval_env.close()


if __name__ == "__main__":
    main()
import hydra
import logging
from env_wrappers.env_wrapper import wrap_env, init_env, get_name
from combined.combined import Combined


@hydra.main(config_path="./config", config_name="cfg_playtable")
def main(cfg):
    # Auto generate names given dense, aff-mask, aff-target
    log = logging.getLogger(__name__)
    cfg.model_name = get_name(cfg, cfg.model_name)
    max_ts = cfg.agent.learn_config.max_episode_length
    for i in range(cfg.repeat_training):
        training_env = init_env(cfg.env)
        # Switch between RL and model-based distance in mts
        training_env.target_radius = 0.25
        training_env = wrap_env(training_env, max_ts,
                                train=True, affordance=cfg.affordance,
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
                         target_search_mode="env")
        model.learn(**cfg.agent.learn_config)
        training_env.close()
        # eval_env.close()


if __name__ == "__main__":
    main()
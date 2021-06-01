from .observation_wrapper import ObservationWrapper
from .reward_wrapper import RewardWrapper


def wrap_env(env, **args):
    env = ObservationWrapper(env, **args)
    env = RewardWrapper(env)
    return env

# class EnvWrapper():
#     def __init__(self, env, **args):
#         env = ObservationWrapper(env, **args)
#         env = RewardWrapper(env)
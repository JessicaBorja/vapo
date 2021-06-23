import torch
import torch.nn as nn
import torch.nn.functional as F
from sac_agent.sac_utils.utils import get_activation_fn
from sac_agent.networks.networks_common import \
     get_pos_shape, get_depth_network, get_img_network, \
     get_gripper_network, get_concat_features


# q function
class CriticNetwork(nn.Module):
    def __init__(self, state_dim, action_dim,
                 activation="relu", hidden_dim=256, **kwargs):
        super(CriticNetwork, self).__init__()
        self.fc1 = nn.Linear(state_dim + action_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.q = nn.Linear(hidden_dim, 1)
        self._activation = get_activation_fn(activation)

    def forward(self, states, actions):
        x = torch.cat((states, actions), -1)
        x = self._activation(self.fc1(x))
        x = self._activation(self.fc2(x))
        return self.q(x).squeeze()


class CNNCritic(nn.Module):
    def __init__(self, obs_space, action_dim, affordance=None,
                 hidden_dim=256, activation="relu"):
        super(CNNCritic, self).__init__()
        _tcp_pos_shape = get_pos_shape(obs_space, "robot_obs")
        _target_pos_shape = get_pos_shape(obs_space, "detected_target_pos")
        _distance_shape = get_pos_shape(obs_space, "target_distance")
        self.cnn_depth = get_depth_network(
                        obs_space,
                        out_feat=16,
                        activation=activation)
        self.cnn_img = get_img_network(
                            obs_space,
                            out_feat=16,
                            activation=activation,
                            affordance_cfg=affordance)
        self.cnn_gripper = get_gripper_network(
                            obs_space,
                            out_feat=16,
                            activation=activation,
                            affordance_cfg=affordance)
        out_feat = 0
        for net in [self.cnn_img, self.cnn_depth, self.cnn_gripper]:
            if(net is not None):
                out_feat += 16
        out_feat += _tcp_pos_shape + _target_pos_shape + _distance_shape
        out_feat += action_dim

        self._activation = activation
        self.fc1 = nn.Linear(out_feat, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.q = nn.Linear(hidden_dim, 1)
        self.aff_cfg = affordance

    def forward(self, states, actions):
        features = get_concat_features(self.aff_cfg,
                                       states,
                                       self.cnn_img,
                                       self.cnn_depth,
                                       self.cnn_gripper)
        x = torch.cat((features, actions), -1)
        x = F.elu(self.fc1(x))
        x = F.elu(self.fc2(x))
        x = self.q(x).squeeze()
        return x

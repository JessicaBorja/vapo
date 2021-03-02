import torch
import torch.nn as nn
import torch.nn.functional as F
from sac_agent.sac_utils.utils import get_activation_fn
import numpy as np


def get_pos_shape(obs_space):
    _obs_space_keys = list(obs_space.spaces.keys())
    _position_shape = ("robot_obs" in _obs_space_keys)
    if("robot_obs" in _obs_space_keys):
        _position_shape = obs_space['robot_obs'].shape[-1]
        return _position_shape
    return 0


def get_depth_network(obs_space, out_feat, activation):
    _obs_space_keys = list(obs_space.spaces.keys())
    _activation_fn = get_activation_fn(activation)
    if("depth_obs" in _obs_space_keys):
        _img_size = obs_space["depth_obs"].shape[-1]
        return CNNCommon(
            1, _img_size,
            out_feat=out_feat,
            activation=_activation_fn)
    return None


def get_gripper_network(obs_space, out_feat, activation):
    _obs_space_keys = list(obs_space.spaces.keys())
    _activation_fn = get_activation_fn(activation)
    if("gripper_img_obs" in _obs_space_keys):
        _history_length = obs_space['gripper_img_obs'].shape[0]
        _img_size = obs_space["gripper_img_obs"].shape[-1]
        return CNNCommon(
            _history_length, _img_size,
            out_feat=out_feat,
            activation=_activation_fn)
    return None


def get_img_network(obs_space, out_feat, activation):
    _obs_space_keys = list(obs_space.spaces.keys())
    _activation_fn = get_activation_fn(activation)
    if("img_obs" in _obs_space_keys):
        _history_length = obs_space['img_obs'].shape[0]
        _img_size = obs_space['img_obs'].shape[-1]
        return CNNCommon(
            _history_length, _img_size,
            out_feat=out_feat,
            activation=_activation_fn)
    return None


def get_concat_features(obs, cnn_img, cnn_depth=None, cnn_gripper=None):
    img = obs['img_obs']
    features = cnn_img(img)
    if("depth_obs" in obs):
        depth_features = cnn_depth(obs['depth_obs'])
        features = torch.cat((features, depth_features), dim=-1)
    if("gripper_img_obs" in obs):
        gripper_features = cnn_gripper(obs['gripper_img_obs'])
        features = torch.cat((features, gripper_features), dim=-1)
    if("robot_obs" in obs):
        features = torch.cat((features, obs['robot_obs']), dim=-1)
    return features


# cnn common takes the function directly, not the str
class CNNCommon(nn.Module):
    def __init__(self, in_channels, input_size, out_feat, activation=F.relu):
        super(CNNCommon, self).__init__()
        w, h = self.calc_out_size(input_size, input_size, 8, 0, 4)
        w, h = self.calc_out_size(w, h, 4, 0, 2)
        w, h = self.calc_out_size(w, h, 3, 0, 1)

        # self.conv1 = nn.Conv2d(in_channels, 32, 8, stride=4)
        # self.conv2 = nn.Conv2d(32, 64, 4, stride=2)
        # self.conv3 = nn.Conv2d(64, 64, 3, stride=1)
        # self.fc1 = nn.Linear(w*h*64, out_feat)

        self.conv1 = nn.Conv2d(in_channels, 16, 8, stride=4)
        self.conv2 = nn.Conv2d(16, 32, 4, stride=2)
        self.conv3 = nn.Conv2d(32, 64, 3, stride=1)
        self.spatial_softmax = SpatialSoftmax(h, w)
        self.fc1 = nn.Linear(2*64, out_feat)  # spatial softmax output

        self._activation = activation

    def forward(self, x):
        if(len(x.shape) == 3):
            x = x.unsqueeze(0)
        # batch_size = x.shape[0]
        # x = self._activation(self.conv1(x))
        # x = self._activation(self.conv2(x))
        # x = self._activation(self.conv3(x))
        # x = self.fc1(x.view(batch_size,-1)).squeeze() #bs, out_feat

        x = self._activation(self.conv1(x))
        x = self._activation(self.conv2(x))
        x = self.spatial_softmax(self.conv3(x))
        x = self.fc1(x).squeeze()  # bs, out_feat
        return x

    def calc_out_size(self, w, h, kernel_size, padding, stride):
        width = (w - kernel_size + 2*padding)//stride + 1
        height = (h - kernel_size + 2*padding)//stride + 1
        return width, height


class SpatialSoftmax(nn.Module):
    # reference: https://arxiv.org/pdf/1509.06113.pdf
    # https://github.com/naruya/spatial_softmax-pytorch
    # https://github.com/cbfinn/gps/blob/82fa6cc930c4392d55d2525f6b792089f1d2ccfe/python/gps/algorithm/policy_opt/tf_model_example.py#L168
    def __init__(self, num_rows, num_cols):
        super(SpatialSoftmax, self).__init__()

        self.num_rows = num_rows
        self.num_cols = num_cols

        x_map = np.empty([num_rows, num_cols], np.float32)
        y_map = np.empty([num_rows, num_cols], np.float32)

        for i in range(num_rows):
            for j in range(num_cols):
                x_map[i, j] = (i - num_rows / 2.0) / num_rows
                y_map[i, j] = (j - num_cols / 2.0) / num_cols

        self.x_map = torch.from_numpy(
                        np.array(x_map.reshape((-1)),
                                 np.float32)).cuda()  # W*H
        self.y_map = torch.from_numpy(
                        np.array(x_map.reshape((-1)),
                                 np.float32)).cuda()  # W*H

    def forward(self, x):
        # batch, C, W*H
        x = x.view(x.shape[0], x.shape[1], x.shape[2]*x.shape[3])
        x = F.softmax(x, dim=2)  # batch, C, W*H
        fp_x = torch.matmul(x, self.x_map)  # batch, C
        fp_y = torch.matmul(x, self.y_map)  # batch, C
        x = torch.cat((fp_x, fp_y), 1)
        return x  # batch, C*2

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision
from torch.utils.tensorboard import SummaryWriter
from torch.distributions import Normal
from networks.common_archs import CNNCommon
from utils.utils import tt, get_activation_fn

#q function     
class CriticNetwork(nn.Module):
  def __init__(self, state_dim, action_dim, activation = "relu", hidden_dim=256 ):
    super(CriticNetwork, self).__init__()
    self.fc1 = nn.Linear(state_dim + action_dim, hidden_dim)
    self.fc2 = nn.Linear(hidden_dim, hidden_dim)
    self.q = nn.Linear(hidden_dim, 1)
    self._non_linearity = get_activation_fn(activation)

  def forward(self, states, actions):
    x = torch.cat((states,actions), -1)
    x = self._non_linearity(self.fc1(x))
    x = self._non_linearity(self.fc2(x))
    return self.q(x).squeeze()

#q function     
class CNNCritic(nn.Module):
  def __init__(self, state_dim, action_dim, use_img, use_pos=False, use_depth=False,\
                 hidden_dim=256, activation = "relu"):
    super(CNNCritic, self).__init__()
    self._use_pos = use_pos
    self._use_depth = use_depth
    self._non_linearity = get_activation_fn(activation)
    #Image obs net
    _history_length = state_dim['rgb_obs'].shape[0]
    _img_size = state_dim['rgb_obs'].shape[-1]

    if(use_pos):
      _position_shape = state_dim['position'].shape[0]
    else:
      _position_shape = 0
    
    if(use_depth):
      self.cnn_depth = CNNCommon(1, _img_size, out_feat = 8, non_linearity = self._non_linearity)
      self.cnn_img = CNNCommon( _history_length, _img_size, out_feat = 8, non_linearity = self._non_linearity)
    else:
      self.cnn_img = CNNCommon( _history_length, _img_size, out_feat = 16, non_linearity = self._non_linearity)

    self.fc1 = nn.Linear(16 + _position_shape + action_dim, hidden_dim)
    self.q = nn.Linear(hidden_dim, 1)

  def forward(self, states, actions):
    img, depth, pos = states['rgb_obs'], states['depth_obs'], states['position']
    features = self.cnn_img(img)
    if(self._use_depth):
      depth_features = self.cnn_depth(depth)
      features = torch.cat((features, depth_features), dim=-1)
    if(self._use_pos):
      features = torch.cat((features, pos), dim=-1)

    x = torch.cat((features,actions), -1)
    x = self._non_linearity( self.fc1(x) )
    x = self.q(x).squeeze()
    return x
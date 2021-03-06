import torch
import torch.nn as nn
import torch.nn.functional as F
from ray.rllib.models.modelv2 import ModelV2
from ray.rllib.models.torch.recurrent_net import RecurrentNetwork
from ray.rllib.utils.annotations import override

from exploration.icm import ICMNet

class SmallConvNet(nn.Module):
    """
    Small PyTorch CNN.
    """
    def __init__(self):
        super(SmallConvNet, self).__init__()
        self.conv1 = nn.Conv2d(4, 32, 3, 2, 1)
        self.conv2 = nn.Conv2d(32, 32, 3, 2, 1)
        self.conv3 = nn.Conv2d(32, 32, 3, 2, 1)
        self.conv4 = nn.Conv2d(32, 32, 3, 2, 1)

    def forward(self, x):
        x = F.leaky_relu(self.conv1(x))
        x = F.leaky_relu(self.conv2(x))
        x = F.leaky_relu(self.conv3(x))
        x = F.leaky_relu(self.conv4(x))
        x = x.reshape((-1, 3 * 3 * 32))
        return x

class SmallConvLSTMModel(RecurrentNetwork, nn.Module):
    """
    RLlib small CNN LSTM actor critic model.
    """
    def __init__(self, obs_space, action_space, num_outputs, model_config, name):
        RecurrentNetwork.__init__(self, obs_space, action_space, num_outputs, model_config, name)
        nn.Module.__init__(self)

        self.convnet = SmallConvNet()
        self.conv_features = None
        self.lstm = nn.LSTM(288, 256, batch_first=True)
        self.lstm.bias_ih_l0.data[256:256 * 2].fill_(1)
        self.lstm_features = None
        self.action_branch = nn.Linear(256, num_outputs)
        self.value_branch = nn.Linear(256, 1)

        self.icm_net = ICMNet(4, num_outputs, in_size=288, feat_size=256)

    @override(RecurrentNetwork)
    def forward(self, input_dict, state, seq_lens):
        x = input_dict['obs'].float().permute(0, 3, 1, 2)
        self.conv_features = self.convnet(x)

        input_dict["obs_flat"] = self.conv_features
        return super().forward(input_dict, state, seq_lens)

    @override(RecurrentNetwork)
    def forward_rnn(self, inputs, state, seq_lens):
        self.lstm_features, [h, c] = self.lstm(inputs,
            [torch.unsqueeze(state[0], 0),
             torch.unsqueeze(state[1], 0)])

        action_out = self.action_branch(self.lstm_features)
        return action_out, [torch.squeeze(h, 0), torch.squeeze(c, 0)]

    @override(ModelV2)
    def value_function(self):
        assert self.lstm_features is not None, "must call forward() first"
        value_out = torch.reshape(self.value_branch(self.lstm_features), [-1])
        return value_out

    @override(ModelV2)
    def get_initial_state(self):
        h = [
            self.action_branch.weight.new(1, 256).zero_().squeeze(0),
            self.action_branch.weight.new(1, 256).zero_().squeeze(0),
        ]
        return h

    def icm_forward(self, obs, next_obs):
        return self.icm_net(obs.permute(0, 3, 1, 2).float(), next_obs.permute(0, 3, 1, 2).float())

    def icm_fwd_forward(self, actions):
        return self.icm_net.fwd_forward(actions)

    def icm_inv_forward(self, actions):
        return self.icm_net.inv_forward(actions)

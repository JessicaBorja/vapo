import numpy as np
from utils.cam_projections import pixel2world, world2pixel
from utils.img_utils import torch_to_numpy, viz_aff_centers_preds
from affordance_model.segmentator_centers import Segmentator
from omegaconf import OmegaConf
import os
import cv2
import torch


class TargetSearch():
    def __init__(self, env, mode,
                 aff_transforms=None, aff_cfg=None,
                 cam_id=0, initial_pos=None, rand_target=False) -> None:
        self.env = env
        self.mode = mode
        self.uniform_sample = False
        self.cam_id = cam_id
        self.random_target = rand_target
        self.initial_pos = initial_pos
        self.aff_transforms = aff_transforms
        self.affordance_cfg = aff_cfg
        self.aff_net_static_cam = self._init_static_cam_aff_net(aff_cfg)
        self.static_cam_imgs = {}
        if(env.task == "pickup"):
            self.box_mask, self.box_3D_end_points = self.get_box_pos_mask(self.env)

    def compute(self, env=None, *args):
        if(self.mode == "affordance"):
            res = self._compute_target_aff(env, *args)
        else:
            res = self._env_compute_target(env)
        return res

    # Env real target pos
    def _env_compute_target(self, env=None):
        if(not env):
            env = self.env
        # This should come from static cam affordance later on
        target_pos, _ = env.get_target_pos()
        # 2 cm deviation
        target_pos = np.array(target_pos)
        target_pos += np.random.normal(loc=0, scale=0.01,
                                       size=(len(target_pos)))
        area_center = np.array(target_pos) \
            + np.array([0, 0, 0.07])

        # always returns a target position
        no_target = False
        return area_center, target_pos, no_target

    # Aff-center model
    def _compute_target_aff(self, env=None, global_obs_it=0):
        if(not env):
            env = self.env
        # Get environment observation
        cam = env.cameras[self.cam_id]
        obs = env.get_obs()
        depth_obs = obs["depth_obs"][self.cam_id]
        orig_img = obs["rgb_obs"][self.cam_id]

        # Apply validation transforms
        img_obs = torch.tensor(orig_img).permute(2, 0, 1).unsqueeze(0).cuda()
        img_obs = self.aff_transforms(img_obs)

        # Predict affordances and centers
        _, aff_probs, aff_mask, center_dir = \
            self.aff_net_static_cam.forward(img_obs)
        if(env.task == "pickup"):
            aff_mask = aff_mask - self.box_mask
        aff_mask, center_dir, object_centers, object_masks = \
            self.aff_net_static_cam.predict(aff_mask, center_dir)

        # Visualize predictions
        if(env.viz or env.save_images):
            img_dict = viz_aff_centers_preds(orig_img, aff_mask, aff_probs, center_dir,
                                             object_centers, object_masks,
                                             "static", global_obs_it,
                                             self.env.save_images)
            self.static_cam_imgs.update(img_dict)
            global_obs_it += 1

        # To numpy
        aff_probs = torch_to_numpy(aff_probs[0].permute(1, 2, 0))  # H, W, 2
        object_masks = torch_to_numpy(object_masks[0])  # H, W

        # Plot different objects
        no_target = False
        if(len(object_centers) > 0):
            target_px = object_centers[0]
        else:
            # No center detected
            default = self.initial_pos
            no_target = True
            return np.array(default), np.array(default), no_target

        max_robustness = 0
        obj_class = np.unique(object_masks)[1:]
        obj_class = obj_class[obj_class != 0]  # remove background class

        if(self.random_target):
            rand_target = np.random.randint(len(object_centers))
            target_px = object_centers[rand_target]
        else:
            # Look for most likely center
            for i, o in enumerate(object_centers):
                # Mean prob of being class 1 (foreground)
                robustness = np.mean(aff_probs[object_masks == obj_class[i], 1])
                if(robustness > max_robustness):
                    max_robustness = robustness
                    target_px = o

        # Convert back to observation size
        pred_shape = aff_probs.shape[:2]
        orig_shape = depth_obs.shape[:2]
        target_px = target_px.detach().cpu().numpy()
        target_px = (target_px * orig_shape / pred_shape).astype("int64")

        # world cord
        v, u = target_px
        if(self.env.save_images):
            out_img = cv2.drawMarker(np.array(orig_img[:, :, ::-1]),
                                     (u, v),
                                     (0, 255, 0),
                                     markerType=cv2.MARKER_CROSS,
                                     markerSize=12,
                                     line_type=cv2.LINE_AA)
            # cv2.imshow("out_img", out_img)
            # cv2.waitKey(1)
            cv2.imwrite("./static_centers/img_%04d.jpg" % self.global_obs_it,
                        out_img)

        # Compute depth
        target_pos = pixel2world(cam, u, v, depth_obs)

        target_pos = np.array(target_pos)
        area_center = np.array(target_pos) \
            + np.array([0, 0, 0.05])
        return area_center, target_pos, no_target

    def get_box_pos_mask(self, env):
        if(not env):
            env = self.env
        box_pos = env.objects["bin"]["initial_pos"]
        x, y, z = box_pos
        box_top_left = [x, y + 0.08, z + 0.05, 1]
        box_bott_right = [x + 0.23, y - 0.35, z, 1]

        # Static camera 
        cam = env.cameras[self.cam_id]

        u1, v1 = world2pixel(np.array(box_top_left), cam)
        u2, v2 = world2pixel(np.array(box_bott_right), cam)

        shape = (cam.width, cam.height)
        mask = np.zeros(shape, np.uint8)
        mask[v1:v2, u1:u2] = 1

        shape = (self.affordance_cfg.img_size, self.affordance_cfg.img_size)
        mask = cv2.resize(mask, shape)
        # cv2.imshow("box_mask", mask)
        # cv2.waitKey()

        # 1, H, W
        mask = torch.tensor(mask).unsqueeze(0).cuda()
        return mask, (box_top_left, box_bott_right)

    def _init_static_cam_aff_net(self, affordance_cfg):
        path = affordance_cfg.model_path
        aff_net = None
        if(os.path.exists(path)):
            hp = OmegaConf.to_container(affordance_cfg.hyperparameters)
            hp = OmegaConf.create(hp)
            aff_net = Segmentator.load_from_checkpoint(
                                path,
                                cfg=hp)
            aff_net.cuda()
            aff_net.eval()
            print("Static cam affordance model loaded (to find targets)")
        else:
            affordance_cfg = None
            path = os.path.abspath(path)
            raise TypeError(
                "target_search_aff.model_path does not exist: %s" % path)
        return aff_net
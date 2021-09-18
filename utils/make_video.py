import os
import sys
import cv2
import tqdm
import json
parent_dir = os.path.dirname(os.getcwd())
sys.path.insert(0, os.getcwd())
sys.path.insert(0, parent_dir)
from file_manipulation import get_files


def make_video(files, fps=60, video_name="v"):
    h, w, c = cv2.imread(files[0]).shape
    fourcc = cv2.VideoWriter_fourcc(*'X264')
    video = cv2.VideoWriter(
                video_name,
                fourcc,
                fps,
                (w, h))  # 30 fps
    print("writing video to %s" % video_name)
    for f in tqdm.tqdm(files):
        img = cv2.imread(f)
        video.write(img)
    cv2.destroyAllWindows()
    video.release()


def join_val_ep(dataset_dir, cam):
    json_file = os.path.join(dataset_dir, "episodes_split.json")
    with open(json_file) as f:
        ep_data = json.load(f)
    files = []
    for ep in ep_data["validation"].keys():
        img_folder = os.path.join(dataset_dir, ep+"/viz_out/%s_cam/" % cam)
        files += get_files(img_folder, "png")
    files.sort()
    return files


def make_videos(path, cam, val_dir=False):
    if(val_dir):
        video_name = os.path.join(
                    os.path.dirname(path),
                    os.path.basename(path) + "_validation.mp4")
        files = join_val_ep(path, cam)
        make_video(files, fps=60, video_name=video_name)
    else:
        for img_folder in path:
            files = get_files(img_folder, "png")
            if(not files):
                return
            video_name = os.path.join(
                    os.path.dirname(img_folder),
                    os.path.basename(img_folder) + ".mp4")
            make_video(files, fps=60, video_name=video_name)


if __name__ == "__main__":
    # pred_folder = "C:/Users/Jessica/Documents/Proyecto_ssd/tmp/2021-06-21/19-52-03/gripper_dirs"
    # path = ['%s/obj_%d' % (pred_folder, i) for i in range(1, 7)]
    pred_folder = "/mnt/ssd_shared/Users/Jessica/Documents/Proyecto_ssd/datasets/teleop_showcase/episode_00"
    # path = [
    #         "%s/rendering_orig" % pred_folder,
    #         "%s/gripper_dirs" % pred_folder,
    #         "%s/gripper_depth" % pred_folder,
    #         ]
    path = [
            "%s/viz_direction/gripper_cam" % pred_folder,
            "%s/viz_direction/static_cam" % pred_folder,
            ]
    val_dir = False
    make_videos(path, "", val_dir)

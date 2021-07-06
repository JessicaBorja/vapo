import hydra
import json
import numpy as np
import tqdm
import os
import sys
import matplotlib.pyplot as plt
import cv2
from sklearn.cluster import KMeans
parent_dir = os.path.dirname(os.getcwd())
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.getcwd())
sys.path.insert(0, parent_dir+"/VREnv/")
from utils.file_manipulation import get_files, check_file


def plot_clusters(data):
    labels = list(data.keys())
    cm = plt.get_cmap('tab10')
    colors = cm(np.linspace(0, 1, len(labels)))

    # Plot clusters
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    # For each set of style and range settings, plot n random points in the box
    viz_n = -1
    for c, label in zip(colors, labels):
        cluster = np.array(data[label])
        ax.scatter(cluster[:viz_n, 0], cluster[:viz_n, 1], cluster[:viz_n, 2], color=c)

    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    ax.legend(labels)
    plt.show()


def find_clusters(directions):
    data = np.array(list(directions.values()))
    clustering = KMeans(n_clusters=5, random_state=0).fit(data)
    # clustering = DBSCAN(eps=0.03, min_samples=3).fit(data)
    labels = clustering.labels_
    # color to label
    n_labels = np.unique(labels)
    cm = plt.get_cmap('tab10')
    colors = cm(np.linspace(0, 1, len(n_labels)))

    # Plot clusters
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    # For each set of style and range settings, plot n random points in the box
    viz_n = -1
    for c, label in zip(colors, n_labels):
        indices = np.where(labels == label)
        cluster = data[indices]
        ax.scatter(cluster[:viz_n, 0], cluster[:viz_n, 1], cluster[:viz_n, 2], c=c)

    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    plt.show()


# If query_pt within neighborhood of any end_pt in trajectory
def find_tracked_objects(trajectories, query_point, labels_lst, neighborhood=0.04):
    # Last point in trajectory list is last known 3d position
    best_match = -1
    if(len(trajectories) > 0):
        min_dist = 10000 # arbitrary high number

        for label, points in trajectories.items():
            # points (n,3), query_point = (3)
            curr_pt = np.expand_dims(query_point, 0)  # 1, 3
            if(label in labels_lst):  # Track in ep after initialized
                end_point = points[-1]
                distance = np.linalg.norm(end_point - query_point)
                labels_lst.append(label)
            else:
                distance = np.linalg.norm(np.array(points) - curr_pt, axis=-1)

            if np.any(distance < neighborhood):
                dist = min(distance)
                if(dist < min_dist):
                    best_match = label
    return best_match, labels_lst


def label_motion(cfg):
    # Episodes info
    # ep_lens = np.load(os.path.join(cfg.play_data_dir, "ep_lens.npy"))
    ep_start_end_ids = np.load(os.path.join(
        cfg.play_data_dir,
        "ep_start_end_ids.npy"))
    end_ids = ep_start_end_ids[:, -1]

    # Iterate rendered_data
    # Sorted files
    files = get_files(cfg.play_data_dir, "npz")
    positions = {}

    start_counter = 0
    sample_freq = 10  # How many ts let pass before computing direction
    past_action = 1
    start_point = None
    trajectories = {}
    curr_obj = None

    n_episodes = 1
    episode = 0
    initialized_labels = []
    files = files[:end_ids[n_episodes - 1]]
    max_classes = 6
    for idx, filename in enumerate(tqdm.tqdm(files)):
        data = check_file(filename)
        if(data is None):
            continue  # Skip file

        _, tail = os.path.split(filename)

        # Initialize img, mask, id
        point = data['robot_obs'][:3]
        rgb_img = data['rgb_static'][:, :, ::-1]
        rgb_img = cv2.resize(rgb_img, (300, 300))
        cv2.imshow("Static", rgb_img)
        cv2.waitKey(1)

        # Start of interaction
        ep_id = int(tail[:-4].split('_')[-1])
        end_of_ep = ep_id >= end_ids[0] + 1 and len(end_ids) > 1
        if(data['actions'][-1] == 0 or end_of_ep):  # open gripper
            # Get mask for static images
            # open -> closed
            if(past_action == 1):
                start_counter += 1
                start_point = point

                # New object tracking
                curr_obj, initialized_labels = \
                    find_tracked_objects(trajectories, point, initialized_labels)
                if(curr_obj == -1):
                    curr_obj = len(trajectories.items())
                    trajectories[curr_obj] = [list(start_point)]
                else:
                    trajectories[curr_obj].append(list(start_point))
            else:
                # mask on close
                # Was closed and remained closed
                # Last element in gripper_hist is the newest
                start_counter += 1
                if(start_counter >= sample_freq):
                    # print("labeling frames hist")
                    direction = point - start_point
                    start_point = point
                    trajectories[curr_obj].append(list(point))
        # Open gripper
        else:
            # Closed -> open transition
            if(past_action == 0):
                if(curr_obj is not None):
                    trajectories[curr_obj].append(list(point))
                start_counter = 0

        # Only collect trajectories for a given number of episodes
        if(episode == n_episodes):
            break

        # Reset everything
        if(end_of_ep):
            end_ids = end_ids[1:]
            past_action = 1  # Open
            episode += 1
            initialized_labels = []

        past_action = data['actions'][-1]

    save_dirs = os.path.join(cfg.output_dir, "trajectories.json")
    with open(save_dirs, 'w') as json_file:
        print("saving to: %s" % save_dirs)
        json.dump(trajectories, json_file, indent=4, sort_keys=True)
    return trajectories


def load_json(path):
    with open(path) as json_file:
        data = json.load(json_file)
    return data


@hydra.main(config_path="../config", config_name="cfg_datacollection")
def main(cfg):
    pos = label_motion(cfg)
    # pos = load_json('/mnt/ssd_shared/Users/Jessica/Documents/Proyecto_ssd/datasets/tmp_test/trajectories.json')
    # pos = load_json("C:/Users/Jessica/Documents/Proyecto_ssd/datasets/tmp_test/trajectories_3objs.json")
    plot_clusters(pos)


if __name__ == "__main__":
    main()

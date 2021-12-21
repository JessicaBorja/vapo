import numpy as np
from scipy.spatial.transform.rotation import Rotation as R


def np_quat_to_scipy_quat(quat):
    """wxyz to xyzw"""
    return np.array([quat.x, quat.y, quat.z, quat.w])


def pos_orn_to_matrix(pos, orn):
    """
    :param pos: np.array of shape (3,)
    :param orn: np.array of shape (4,) -> quaternion xyzw
                np.quaternion -> quaternion wxyz
                np.array of shape (3,) -> euler angles xyz
    :return: 4x4 homogeneous transformation
    """
    mat = np.eye(4)
    if isinstance(orn, np.quaternion):
        orn = np_quat_to_scipy_quat(orn)
        mat[:3, :3] = R.from_quat(orn).as_matrix()
    elif len(orn) == 4:
        mat[:3, :3] = R.from_quat(orn).as_matrix()
    elif len(orn) == 3:
        mat[:3, :3] = R.from_euler('xyz', orn).as_matrix()
    mat[:3, 3] = pos
    return mat


def get_depth_around_point(point, depth):
    for width in range(5):
        area = depth[point[1] - width: point[1] + width + 1, point[0] - width: point[0] + width + 1]
        area[np.where(area == 0)] = np.inf
        if np.all(np.isinf(area)):
            continue
        new_point = np.array([point[1], point[0]]) + np.array(np.unravel_index(area.argmin(), area.shape)) - width

        assert depth[new_point[0], new_point[1]] != 0
        return (new_point[1], new_point[0]), True
    return None, False
import numpy as np
from utilities_sim import quadcopter_plot

''' name: Robotarium Communication Interface File
    author: Christopher Banks and Yousef Emam
    date: 09/15/2020
    description: Contains files for simulating the communication framework of the Robotarium for
    the quadcopters. DO NOT EDIT'''


class RobotariumCommunication(object):
    def __init__(self, robotarium_sim_environment, index):
        self.name = 'crazyflie_{0}'.format(index)
        self.id = index
        self.first_flag = True
        self.sim_env = robotarium_sim_environment
        self.quadcopter_communicate = None
        self.thrust_hover = 34000  # arbitrary value
        self.state = np.zeros(12)

    def set_initial_random_pose(self):
        pose_x = (1.3 - (-1.3))*np.random.sample() + (-1.3)
        pose_y = (1.3 - (-1.3))*np.random.sample() + (-1.3)
        pose_z = 0
        pose = np.array([pose_x, pose_y, pose_z])
        return pose

    def get_init_pose(self):
        if self.first_flag is True:
            self.first_flag = False
            pose = self.set_initial_random_pose()
            self.quadcopter_communicate = quadcopter_plot.QuadPlotObject(self.sim_env, pose)
            orientation = np.zeros((1, 3))
            return pose, orientation

    def set_init_pose(self, initial_pose):
        if self.first_flag is True:
            self.first_flag = False
            self.quadcopter_communicate = quadcopter_plot.QuadPlotObject(self.sim_env, initial_pose)
            self.state = np.zeros(12)
            self.state[:3] = initial_pose

    def set_pose(self, pose, sim_env, roll=0, pitch=0, yaw=0, thrust=0):

        self.quadcopter_communicate.update(sim_env, pose, roll, pitch, yaw)
        self.state[:3] = pose
        self.state[3:6] = np.array([roll, pitch, yaw])
        self.state[6:] = 0

    def get_pose_and_orientation(self):

        pose = self.state[:3]
        orientation = self.state[3:6]

        return pose, orientation

    def get_state(self):

        return self.state

    def set_state(self, state, sim_env):

        self.quadcopter_communicate.update(sim_env, state[:3], state[3], state[4], state[5])
        self.state = state



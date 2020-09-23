#!/usr/bin/env python
import random as rand
import numpy as np
import matplotlib.pyplot as plt
import mpl_toolkits.mplot3d.axes3d as Dim3
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from control import acker
from cvxopt import matrix, solvers
import time
import pickle
from utilities_sim.actuation import vel_back_step, gen_splines
from utilities_sim.quadcopter_model import QuadcopterObject

TIMEOUT_FLAG = False
TIMEOUT_TIME = 30

''' name: Robotarium Simulation File
    authors: Christopher Banks & Yousef Emam
    date: 09/08/2020
    description: Contains files for simulating quadcopter (QuadcopterObject) and quadcopter dynamics.'''


# contains a simulated version of the Robotarium Environment used for the quadcopters.
# quadcopters are simulated as a chain of integrators with a control input designed to be
# 3x differentiable in order to generate the necessary states
# to back out the control inputs from the differentially flat properties of the quadcopter dynamics.
class RobotariumEnvironment(object):
    def __init__(self, number_of_agents=rand.randint(3, 10), save_data=True, barriers=True):

        # High level parameters
        self.number_of_agents = number_of_agents
        self.robotarium_simulator_plot = None
        self.barriers = barriers  # Bool indicating whether to ensure safety using CBFs
        self.save_flag = save_data  # flag indicating whether to save the data relating to the experiment
        self.count = 0  # experiment iteration count
        solvers.options['show_progress'] = False  # verbose option for the CBF QP solver
        # State related parameters
        self.initial_poses = np.array([])
        self.poses = np.array([])  # Chain of Integrator Model (xyz) state
        self.desired_poses = np.zeros((self.number_of_agents, 3))  # User desired poses
        self.crazyflie_objects = {}
        self.time = time.time()
        self.x_state = dict()
        self.vel_prev = dict()  # for backstepping, vel_prev[i] = np.array((1,3))
        self.des_vel_prev = dict()  # for backstepping
        self.desired_vels = np.zeros((self.number_of_agents, 3))  # User desired velocities (used for backstepping)
        self.u = dict()  # control inputs to the robots
        self.orientation_real = dict()  # Actual orientation of the quadcopter
        self.pose_real = dict()  # Actual State of the quadcopter
        self.dt = 0.02  # time step size
        # Data recording
        self.time_record = dict()  # time data
        self.x_record = dict()  # x data
        self.input_record = dict()  # u data
        self.orientation_record = dict()  # orientation data
        # Matrices for integrator model used by CBFs
        self.AA = np.array([[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]])
        self.bb = np.array([[0], [0], [0], [1]])
        self.Kb = np.asarray(acker(self.AA, self.bb, [-12.2, -12.4, -12.6, -12.8]))  # Gains
        self.bds = np.array([[-1.3, -1.3, 0.0], [1.3, 1.3, 1.8]])  # 2x3 matrix, bds[0] and bds[1] are neg and pos x,
        # y,z bounds respectively.


    def get_quadcopter_poses(self):
        """Get quadcopter poses.

        Returns:
            poses (ndarray): Array of size (N,3). x,y,z positions of the quadrotors.

        """
        poses = np.zeros((self.number_of_agents, 3))
        for i in range(self.number_of_agents):
            poses[i], _ = self.crazyflie_objects[i].get_pose_and_orientation()
        return poses

    def set_desired_poses(self, poses):
        """Set the desired poses for the quadcopters.

        Args:
            poses (ndarray): Array of size (N,3).

        Returns:
`
        """

        self.desired_poses = poses

    def build(self):
        """Builds the robotarium object and creates quadcopter object (includes plotting) for each quadcopter.

        Returns:

        """

        try:
            assert self.number_of_agents > 0
        except AssertionError:
            raise Exception("number of agents must be greater than 0!!")

        self.robotarium_simulator_plot = self.plot_robotarium()

        # Initial poses (x,y,z) not specified by the user (Assign random poses)
        if len(self.initial_poses) == 0:
            self.initial_poses = np.zeros((self.number_of_agents, 3))
            self.initial_poses[:, 0] = (1.3 - (-1.3)) * np.random.sample(self.number_of_agents) + (-1.3)  # x
            self.initial_poses[:, 1] = (1.3 - (-1.3)) * np.random.sample(self.number_of_agents) + (-1.3)  # y

        # Initialize object properties
        for i in range(self.number_of_agents):
            self.crazyflie_objects[i] = QuadcopterObject(self.robotarium_simulator_plot, self.initial_poses[i], index=i, dt=self.dt)
            self.poses = self.initial_poses
            self.x_state[i] = np.zeros((4, 3))
            self.x_state[i][0] = self.poses[i]
            self.vel_prev[i] = np.zeros((1, 3))
            self.des_vel_prev[i] = np.zeros((1, 3))

    def hover_quads_at_initial_poses(self, takeoff_time=10.0):
        """

        Args:
            takeoff_time (float):

        Returns:

        """

        reached_des_flag = np.zeros((self.number_of_agents))
        t0 = time.time()
        self.desired_poses = np.zeros((self.number_of_agents, 3))
        for i in range(self.number_of_agents):
            self.desired_poses[i] = self.initial_poses[i]
            self.x_state[i] = np.zeros((4, 3))
            self.x_state[i][0] = self.poses[i]

        while np.sum(reached_des_flag) < self.number_of_agents:
            t = time.time()
            s = min((t - t0) / takeoff_time, 1.0)  # kind of a sudo-gain
            for i in range(self.number_of_agents):
                reached_des_flag[i], self.poses[i] = self.crazyflie_objects[i].hover_bot(self.desired_poses[i], s, self.robotarium_simulator_plot)
            plt.pause(0.001)

        for i in range(self.number_of_agents):
            self.x_state[i] = np.zeros((4, 3))
            self.x_state[i][0] = self.poses[i]



    def update_poses(self, velocities=False):
        """Update the state of the quads. User specifies desired pose, at least 3 times differentiable trajectory will be
        be computed to reach that desired pose. Here, only a single step is taken to reach the first point in the
        computed trajectory computed by the spline. #TODO: is this correct?
            1) iterate over quadcopter objects
            2) send desired points to quads
            3) make interpolation points from desired point and make max velocity can fly at
            4) quadcopter updates dynamics from current points based on interpolation point
            5) only computes a single iteration from the trajectory computed in the spline
            6) one should call this function until desired poses are acquired which is signaled by the return flag

        Args:
            velocities (bool): Determines the control mode, either we give the velocities to the quads as commands or
            next pose.

        Returns:

        """

        if velocities is True:
            for i in range(self.number_of_agents):
                desired_point = vel_back_step(self.x_state[i], self.vel_prev[i], self.desired_vels[i], self.des_vel_prev[i])
                self.u[i] = desired_point
        else:
            desired_trajs = dict()
            for i in range(self.number_of_agents):
                if np.linalg.norm((self.x_state[i][0, :] - self.desired_poses[i])) == 0:
                    desired_trajs[i] = np.zeros((4, 3))
                    desired_trajs[i][0, :] = self.desired_poses[i]
                    desired_trajs[i] = np.stack((desired_trajs[i], desired_trajs[i]), axis=0)
                else:
                    desired_trajs[i] = gen_splines(self.x_state[i][0, :], self.desired_poses[i])


            # The desired trajectory for each quadrotor is of shape (n_spline, 4, 3), where n is the number of points
            # in the spline, 4 is the number of derivatives (size of the integrator state) and 3 is for x, y, z.
            # So what we are doing here is generating the spline, then synthesizing the control necessary to follow
            # the first point of the trajectory generated by the spline.
            for i in range(self.number_of_agents):
                self.u[i] = desired_trajs[i][0][3, :] - np.dot(self.Kb, self.x_state[i] - desired_trajs[i][0])

        # Threshold velocities
        for i in range(self.number_of_agents):
            if np.linalg.norm(self.u[i]) > 1e4:
                self.u[i] = (self.u[i] / np.linalg.norm(self.u[i])) * 1e4

        # Ensure Safety using Barriers Functions
        if self.barriers is True:
            self.u = self.Safe_Barrier_3D(self.x_state, self.u)

        # Update object properties
        for i in range(self.number_of_agents):
            xd = dict()
            xd[i] = np.dot(self.AA, self.x_state[i]) + np.dot(self.bb, self.u[i])
            self.x_state[i] = self.x_state[i] + xd[i]*self.dt
            u_moments = self.crazyflie_objects[i].go_to(self.x_state[i], desired_orientation=None)
            self.crazyflie_objects[i].forward_model(self.robotarium_simulator_plot, u_moments)
            self.poses[i] = self.x_state[i][0, :]
            self.pose_real[i], self.orientation_real[i] = self.crazyflie_objects[i].get_pose_and_orientation()
            self.vel_prev[i] = self.x_state[i][1, :]
            self.des_vel_prev[i] = self.desired_vels[i]

        # Data recording
        plt.pause(0.02)
        self.time_record[self.count] = str(self.run_time())
        self.x_record[self.count] = self.pose_real
        self.orientation_record[self.count] = self.orientation_real
        self.input_record[self.count] = self.u.copy()

        self.count += 1

    def check_timeout(self):
        """Check if the experiment ran longer than TIMEOUT_TIME (5 minutes by default).

        Returns:
            TIMEOUT_FLAG (bool): True if experiment ran longer than TIMEOUT_TIME

        """

        global TIMEOUT_FLAG, TIMEOUT_TIME
        if self.run_time() > TIMEOUT_TIME:
            TIMEOUT_FLAG = True
        return TIMEOUT_FLAG

    def run_time(self):
        """Returns how long the experiment has been running for.

        Returns:
            time_now (float): Time in secs since the start of the experiment.

        """
        time_now = time.time() - self.time
        return time_now

    def save_data(self):
        """Saves the experiment data (time, poses, orientation and input) into a pickle file.

        Returns:

        """
        time_stamp = time.strftime('%d_%B_%Y_%I:%M%p')
        file_n = 'quads_robotarium_'+ time_stamp +'.pckl'
        arrays = [self.time_record, self.x_record, self.orientation_real, self.input_record]
        with open(file_n, 'wb') as file:
            pickle.dump(arrays, file)

    def Safe_Barrier_3D(self, x, u=None, zscale=3, gamma=5e-1):
        """Barrier function method: creates a ellipsoid norm around each quadcopter with a z=0.3 meters
        A QP-solver is used to solve the inequality Lgh*(ui-uj) < gamma*h + Lfh.

        Args:
            x (ndarray): State of the robots of size (?,?,?)
            u (dict): User specified desired jerks (x,y,z), keys are quad indices and values are of size (3,)
            zscale (float): Scaling of the z-axis
            gamma (float): Barrier Gain

        Returns:
            u_safe (ndarray): Minimally altered inputs to guarantee safety (same size as u).
        """


        if u:
            u = u.copy()
        else:
            u = self.u

        Kb = self.Kb
        N = len(u)
        Ds = 0.3
        H = 2 * np.eye(3 * N)
        f = -2 * np.reshape(np.hstack(u.values()), (3 * N, 1))
        A = np.empty((0, 3 * N))
        b = np.empty((0, 1))
        for i in range(N - 1):
            for j in range(i + 1, N):
                pr = np.multiply(x[i][0, :] - x[j][0, :], np.array([1, 1, 1.0 / zscale]))
                prd = np.multiply(x[i][1, :] - x[j][1, :], np.array([1, 1, 1.0 / zscale]))
                prdd = np.multiply(x[i][2, :] - x[j][2, :], np.array([1, 1, 1.0 / zscale]))
                prddd = np.multiply(x[i][3, :] - x[j][3, :], np.array([1, 1, 1.0 / zscale]))
                h = np.linalg.norm(pr, 4) ** 4 - Ds ** 4
                hd = sum(4 * pr ** 3 * prd)
                hdd = sum(12 * pr ** 2 * prd ** 2 + 4 * pr ** 3 * prdd)
                hddd  = sum(24*pr*prd**3 + 36*pr**2*prd*prdd + 4*pr**3*prddd)
                Lfh = sum(24*pr*prd**3 + 36*pr**2*prd*prdd + 4*pr**3*prddd)
                Lgh = 4 * pr ** 3 * np.array([1, 1, 1.0 / zscale])
                Anew = np.zeros((3 * N,))
                Anew[3 * i:3 * i + 3] = - Lgh
                Anew[3 * j:3 * j + 3] = Lgh
                bnew = gamma * np.dot(Kb, [h, hd, hdd, hddd]) + Lfh
                A = np.vstack([A, Anew])
                b = np.vstack([b, bnew])

        # Robotarium Boundaries
        bds = self.bds

        Ds_bounds = 0.05

        for i in range(N):
            Anew = np.zeros((3, 3 * N))  # np.zeros((6, 3 * N))
            bnew = np.zeros((3, 1))  # np.zeros((6, 1))

            # Both Boundaries (assuming symmetric)
            pr = x[i][0, :]
            prd = x[i][1, :]
            prdd = x[i][2, :]
            prddd = x[i][3, :]
            hs = - pr ** 4 + (bds[1, :] - Ds_bounds) ** 4
            hds = - 4 * pr ** 3 * prd
            hdds = - 12 * pr ** 2 * prd ** 2 - 4 * pr ** 3 * prdd
            hddds = - 24 * pr * prd ** 3 - 36 * pr ** 2 * prd * prdd - 4 * pr ** 3 * prddd

            Lfh = - 24 * pr * prd ** 3 - 36 * pr ** 2 * prd * prdd - 4 * pr ** 3 * prddd
            Lgh = - 4 * pr ** 3

            Anew[:3, 3 * i:3 * i + 3] = - np.diag(Lgh)
            bnew[:3] = (gamma * np.dot(Kb, np.vstack((hs, hds, hdds, hddds))) + Lfh).T

            A = np.vstack([A, Anew])
            b = np.vstack([b, bnew])

        G = np.vstack([A, -np.eye(3 * N), np.eye(3 * N)])
        amax = 1e4
        h = np.vstack([b, amax * np.ones((3 * N, 1)), amax * np.ones((3 * N, 1))])
        sol = solvers.qp(matrix(H), matrix(f), matrix(G), matrix(h))


        x = sol['x']

        for i in range(N):
            u[i] = np.reshape(x[3 * i:3 * i + 3], (1, 3))

        if sol['status'] == 'unknown':
            raise Warning('Control Barrier Function QP could not be solved.')

        return u

    def plot_robotarium(self, d_buffer=0.1):
        """Initialize plot of the robotarium environment

        Returns:
            ax (Dim3.Axes3D): Robotarium plot

        """

        fig = plt.figure()
        ax = Dim3.Axes3D(fig)

        # Set Axes
        ax.set_aspect('equal')
        ax.set_xlim3d([self.bds[0][0] - d_buffer, self.bds[1][0] + d_buffer])
        ax.set_xlabel('x', fontsize=10)
        ax.set_ylim3d([self.bds[0][1] - d_buffer, self.bds[1][1] + d_buffer])
        ax.set_ylabel('y', fontsize=10)
        ax.set_zlim3d([self.bds[0][2] - d_buffer, self.bds[1][2] + d_buffer])
        ax.set_zlabel('z', fontsize=10)
        ax.tick_params(labelsize=10)

        # Plot Boundary
        # vertices of a pyramid
        v = np.zeros((8, 3))
        for i in range(2):
            for j in range(2):
                for k in range(2):
                    v[4*i+2*j+k] = [self.bds[i, 1], self.bds[j, 1], self.bds[k, 2]]

        # Plot Vertices
        ax.scatter3D(v[:, 0], v[:, 1], v[:, 2])

        # Generate faces
        faces = []
        for i in range(5):
            for j in range(i+1, 6):
                for k in range(j+1, 7):
                    for l in range(k+1, 8):
                        if np.any(np.all(v[[i, j, k, l], :] == v[[i], :], 0)):
                            faces.append([v[l], v[k], v[i], v[j]])

        # Plot Faces
        face_color = [0.5, 0.5, 1]  # alternative: matplotlib.colors.rgb2hex([0.5, 0.5, 1])
        collection = Poly3DCollection(faces, linewidths=1, edgecolors=face_color, alpha=0.05, facecolors=None)
        collection.set_facecolor(face_color)
        ax.add_collection3d(collection)

        return ax


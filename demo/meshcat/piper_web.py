#!/usr/bin/env python3
# -*-coding:utf8-*-
import numpy as np
from math import pi
import transforms3d.euler as euler
from scipy.spatial.transform import Rotation
import sys
import select
import time
import json
from piper_sdk import *
import pinocchio as pin
from scipy.optimize import minimize
import paho.mqtt.client as mqtt
import os
from os.path import dirname, join, abspath
import subprocess
import random  # Import the random module
import threading  # Import the threading module
import logging

# Configure logging
#logging.basicConfig(level=logging.DEBUG,  # Set log level
#                    format='%(asctime)s - %(levelname)s - %(message)s')


from pinocchio.visualize import MeshcatVisualizer

# MQTT Broker Configuration
MQTT_BROKER = "47.96.170.89"
MQTT_PORT = 8003
MQTT_TOPIC_PICO = "arm/pose/robot_test_arm"  # Topic for PICO messages
MQTT_TOPIC_WEB = "arm/pose/web_control"  # Topic for Web messages
# MQTT_CLIENT_ID = "piper_web"  # No longer a constant

# Robot Configuration
FACTOR = 57290
INITIAL_END_POSE = [0.2, 0, 0.18, 0, pi / 2, 0]  # Initial end-effector pose
NUM_JOINTS = 6  # Number of joints you are controlling
CAN_IFACE = "can0"
CAN_BITRATE = "1000000"
CAN_USB_ADDRESS = "1-2.3:1.0"

# Define limits for the end effector pose (adjust as needed)
X_LIMIT = [0.0, 0.3]
Y_LIMIT = [-0.15, 0.15]
Z_LIMIT = [0.1, 0.6]
RX_LIMIT = [-pi / 2, pi / 2]
RY_LIMIT = [pi / 2 - 0.1, pi / 2 + 0.1]  # RY set limit
RZ_LIMIT = [-pi, pi]

# Define the maximum random delta for each component of the end pose
MAX_DELTA_POSITION = 0.001  # Adjust as needed (e.g., 1mm)
MAX_DELTA_ORIENTATION = 0.001  # Adjust as needed (e.g., 0.1 degrees in radians)


def enable_fun(piper: C_PiperInterface):
    """Enables the arm motors and gripper."""
    enable_flag = False
    timeout = 5
    start_time = time.time()
    elapsed_time_flag = False
    while not enable_flag:
        elapsed_time = time.time() - start_time
        print("--------------------")
        enable_flag = all(
            [
                getattr(piper.GetArmLowSpdInfoMsgs(), f"motor_{i + 1}").foc_status.driver_enable_status
                for i in range(NUM_JOINTS)
            ]
        )  # use NUM_JOINTS
        print("使能状态:", enable_flag)
        piper.EnableArm(7)
        piper.GripperCtrl(0, 1000, 0x01, 0)
        print("--------------------")
        if elapsed_time > timeout:
            print("超时....")
            elapsed_time_flag = True
            enable_flag = True
            break
        time.sleep(1)

    if elapsed_time_flag:
        print("程序自动使能超时,退出程序")
        exit(0)


def is_data_available():
    return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [], 0)


def left_to_right_hand(x_left, y_left, z_left, rx_left, ry_left, rz_left):
    """Converts coordinates from a left-handed to a right-handed coordinate system."""
    x_right = z_left
    y_right = -x_left
    z_right = y_left
    r_left = Rotation.from_euler("zyx", [rz_left, ry_left, rx_left])
    rot_matrix_left = r_left.as_matrix()
    transform_matrix = np.array([[0, 0, 1], [-1, 0, 0], [0, 1, 0]])
    transform_matrix_inv = transform_matrix.T
    rot_matrix_right = transform_matrix @ rot_matrix_left @ transform_matrix_inv
    r_right = Rotation.from_matrix(rot_matrix_right)
    rz_right, ry_right, rx_right = r_right.as_euler("zyx")
    return [x_right, y_right, z_right, rx_right, ry_right, rz_right]


def process_message_pico(payload):
    """Processes an MQTT message payload from PICO and extracts end-effector pose and other data."""
    try:
        data = json.loads(payload)
        if "info" in data and isinstance(data["info"], list) and len(data["info"]) == 15:
            (
                x,
                y,
                z,
                qx,
                qy,
                qz,
                qw,
                trigger,
                joystickX,
                joystickY,
                joystickClick,
                buttonA,
                buttonB,
                grip,
                temp,
            ) = data["info"]
            rx, ry, rz = euler.quat2euler([qw, qx, qy, qz], "sxyz")
            endpose = left_to_right_hand(x, y, z, rx, ry, rz)
            #logging.debug(f"Processed PICO message: endpose={endpose}, trigger={trigger}, ...")
            return endpose, int(trigger), joystickX, joystickY, joystickClick, buttonA, buttonB, grip, int(
                temp
            )  # Return temp
        else:
            #logging.warning("Invalid data format from PICO")
            return None, None, None, None, None, None, None, None, None
    except (json.JSONDecodeError, Exception) as e:
        #logging.error(f"Error processing PICO message: {e}", exc_info=True)
        return None, None, None, None, None, None, None, None, None


def process_message_web(payload):
    """Processes an MQTT message payload from the web and extracts end-effector pose delta and other data."""
    try:
        data = json.loads(payload)
        if "info" in data and isinstance(data["info"], list) and len(data["info"]) == 15:
            (
                x,
                y,
                z,
                rx,
                ry,
                rz,
                tmp,  # Discard qx, qy, qz, qw
                trigger,
                joystickX,
                joystickY,
                joystickClick,
                buttonA,
                buttonB,
                grip,
                temp,
            ) = data["info"]
            endpose_delta = [x, y, z, rx, ry, rz]  # DIRECTLY ASSIGN THE FIRST 6 ELEMENTS
            #logging.debug(f"Processed WEB message: endpose_delta={endpose_delta}, trigger={trigger}, ...")

            return endpose_delta, trigger, joystickX, joystickY, joystickClick, buttonA, buttonB, grip, int(
                temp
            )  # Return temp
        else:
            #logging.warning("Invalid data format from WEB")
            return None, None, None, None, None, None, None, None, None
    except (json.JSONDecodeError, Exception) as e:
        #logging.error(f"Error processing WEB message: {e}", exc_info=True)
        return None, None, None, None, None, None, None, None, None


class MQTTHandler:
    def __init__(self, broker, port, client_id_prefix="piper_web"):
        self.broker = broker
        self.port = port
        self.client_id = f"{client_id_prefix}_{random.randint(1000, 9999)}"  # Generate a unique client ID
        self.client = mqtt.Client(client_id=self.client_id)
        self.client.on_connect = self.on_connect
        #self.client.on_message = self.on_message
        self.client.on_message = self._on_message_callback # Use internal callback
        self.endpose = None
        self.endpose_delta = None
        self.trigger = None
        self.joystickX = None
        self.joystickY = None
        self.joystickClick = None
        self.buttonA = None
        self.buttonB = None
        self.grip = None
        self.temp = None  # Store the 'temp' value
        self.control_mode = "web"  # Initial control mode: "pico" or "web"
        self.current_topic = MQTT_TOPIC_WEB  # Start listening to PICO topic
        self._lock = threading.Lock()  # Initialize the lock
        self.message_available = False  # Flag to indicate if a message is available
        self.publish_interval = 0.03  # 30 Hz publish interval
        self.last_publish_time = 0
        self.qos = 1  # Set QoS level

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            #logging.info(f"Connected to MQTT Broker with client ID: {self.client_id}!")
            self.subscribe_to_topic(self.current_topic)
        else:
            print("failed to connect")
            #logging.error(f"Failed to connect, return code {rc}")

    def _on_message_callback(self, client, userdata, msg):
        """Internal callback to handle messages in a thread-safe manner."""
        # Spin off a thread to handle the message
        threading.Thread(target=self._process_message, args=(msg,)).start()

    def _process_message(self, msg):
        """Processes the MQTT message and updates internal state."""
        try:
            if self.control_mode == "pico":
                endpose, trigger, joystickX, joystickY, joystickClick, buttonA, buttonB, grip, temp = (
                    process_message_pico(msg.payload.decode())
                )
                with self._lock:
                    self.endpose = endpose
                    self.endpose_delta = None
                    self.trigger = trigger
                    self.joystickX = joystickX
                    self.joystickY = joystickY
                    self.joystickClick = joystickClick
                    self.buttonA = buttonA
                    self.buttonB = buttonB
                    self.grip = grip
                    self.temp = temp  # Store the temp value
                    self.message_available = True  # Set the flag when a message is received

            elif self.control_mode == "web":
                endpose_delta, trigger, joystickX, joystickY, joystickClick, buttonA, buttonB, grip, temp = (
                    process_message_web(msg.payload.decode())
                )
                with self._lock:
                    self.endpose = None
                    self.endpose_delta = endpose_delta
                    self.trigger = trigger
                    self.joystickX = joystickX
                    self.joystickY = joystickY
                    self.joystickClick = joystickClick
                    self.buttonA = buttonA
                    self.buttonB = buttonB
                    self.grip = grip
                    self.temp = temp  # Store the temp value
                    self.message_available = True  # Set the flag when a message is received

            #else:
                #logging.warning("Unknown control mode in on_message.")  # Add a log message for debugging

        except Exception as e:
            print("connection error")
            #logging.error(f"Error processing message in on_message: {e}", exc_info=True)  # Add logging for any errors

    def connect(self):
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()  # Use loop_start for non-blocking operation
            # self.client.loop_forever() # Can also use loop_forever if you don't need main thread for other things
        except Exception as e:
            print("connection error")
            #logging.error(f"Connection error: {e}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe_to_topic(self, topic):
        """Subscribes to the specified MQTT topic and resets stored data."""
        self.client.unsubscribe(self.current_topic)  # Unsubscribe from the old topic
        self.current_topic = topic
        self.client.subscribe(self.current_topic, qos=self.qos)  # Use the configured QoS
        #logging.info(f"Subscribed to topic: {topic} with QoS {self.qos}")

        # Reset stored data when switching topics
        with self._lock:
            self.endpose = None
            self.endpose_delta = None
            self.trigger = None
            self.joystickX = None
            self.joystickY = None
            self.joystickClick = None
            self.buttonA = None
            self.buttonB = None
            self.grip = None
            self.temp = None  # Reset temp
            self.message_available = False

    def switch_control_mode(self, mode):
        """Switches between PICO and Web control modes."""
        if mode not in ["pico", "web"]:
            #logging.warning("Invalid control mode specified.")
            return

        if mode != self.control_mode:
            self.control_mode = mode
            if mode == "pico":
                self.subscribe_to_topic(MQTT_TOPIC_PICO)
            elif mode == "web":
                self.subscribe_to_topic(MQTT_TOPIC_WEB)
        else:
            print("error")
            #logging.info(f"Already in {mode} control mode.")

    def get_data(self):
        """Returns the appropriate data based on the control mode."""
        with self._lock:
            message_available = self.message_available  # Copy the value under the lock
            self.message_available = False  # Reset the flag
            if self.control_mode == "pico":
                return (
                    self.endpose,
                    self.trigger,
                    self.joystickX,
                    self.joystickY,
                    self.joystickClick,
                    self.buttonA,
                    self.buttonB,
                    self.grip,
                    self.temp,  # Return temp
                    message_available,
                )
            elif self.control_mode == "web":
                return (
                    self.endpose_delta,
                    self.trigger,
                    self.joystickX,
                    self.joystickY,
                    self.joystickClick,
                    self.buttonA,
                    self.buttonB,
                    self.grip,
                    self.temp,  # Return temp
                    message_available,
                )
            else:
                #logging.warning("Unknown control mode in get_data.")
                return None, None, None, None, None, None, None, None, None, False


def cost_function(q, model, data, target_pose):
    """Cost function for IK optimization.  Measures the distance between the current end-effector pose and the target pose."""
    # Create the full joint angle vector, setting the fixed joints to 0
    q_full = np.zeros(model.nq)
    q_full[0] = q[0]  # Joint 0
    q_full[1] = q[1]  # Joint 1
    q_full[2] = q[2]  # Joint 2
    q_full[3] = 0  # Joint 3 is fixed at 0
    q_full[4] = q[3]  # Joint 4
    q_full[5] = 0  # Joint 5 is fixed at 0

    pin.forwardKinematics(model, data, q_full)
    pin.updateFramePlacements(model, data)
    current_pose = data.oMf[model.getFrameId("gripper_base")].homogeneous  # change tool_frame to your frame name.

    # Calculate position error
    #position_error = np.linalg.norm(current_pose[:3, 3] - target_pose[:3, 3])
    position_error = np.linalg.norm(current_pose[:2, 3] - target_pose[:2, 3])*0.1 + np.linalg.norm(current_pose[2, 3] - target_pose[2, 3])

    # Calculate orientation error (using rotation matrix difference)
    rotation_error = np.linalg.norm(current_pose[:3, :3] - target_pose[:3, :3])
    # print("Error",position_error + rotation_error)
    # return position_error + rotation_error*0.12
    return position_error + rotation_error * 0.2


def inverse_kinematics(model, data, target_pose, q_init=None):
    """Inverse kinematics using optimization."""
    if q_init is None:
        q_init = np.zeros(4)  # Initial guess for joint angles, now just 4 joints.

    # Optimization bounds (joint limits) - Optional, but highly recommended
    bounds = [
        (model.lowerPositionLimit[i], model.upperPositionLimit[i]) for i in [0, 1, 2, 4]
    ]  # Only bounds for active joints

    start_time = time.time()

    result = minimize(
        cost_function, q_init, args=(model, data, target_pose), method="SLSQP", bounds=bounds, tol=1e-5
    )  # tol is tolerance
    elapsed_time = time.time() - start_time
    if result.success:
        return result.x, True, elapsed_time
    else:
        return None, False, elapsed_time


def run_can_activation_script():
    """Runs the can_activate.sh script with a strict USB-CAN address check."""
    can_iface = find_can_interface_by_usb_address(CAN_USB_ADDRESS)
    if can_iface != CAN_IFACE:
        print(
            f"CAN interface mismatch: expected {CAN_IFACE}, "
            f"but USB device {CAN_USB_ADDRESS} is mapped to {can_iface}."
        )
        sys.exit(1)

    try:
        subprocess.run(
            ["bash", "can_activate.sh", CAN_IFACE, CAN_BITRATE, CAN_USB_ADDRESS],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        #logging.error(f"Error running can_activate.sh: {e}")
        sys.exit(1)  # Exit if the script fails


def find_can_interface_by_usb_address(expected_usb_address: str) -> str:
    """Finds the CAN interface whose bus-info matches the expected USB address."""
    try:
        result = subprocess.run(
            ["ip", "-br", "link", "show", "type", "can"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        print("Unable to list CAN interfaces.")
        sys.exit(1)

    interfaces = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
    if not interfaces:
        print("No CAN interfaces detected.")
        sys.exit(1)

    for iface in interfaces:
        try:
            info = subprocess.run(
                ["ethtool", "-i", iface],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            continue

        bus_info = ""
        for line in info.stdout.splitlines():
            if line.startswith("bus-info:"):
                bus_info = line.split(":", 1)[1].strip()
                break

        if bus_info == expected_usb_address:
            return iface

    print(
        f"Expected USB-CAN device {expected_usb_address} was not found. "
        "Please verify cable and USB address."
    )
    print("Detected CAN interfaces and bus-info:")
    for iface in interfaces:
        try:
            info = subprocess.run(
                ["ethtool", "-i", iface],
                check=True,
                capture_output=True,
                text=True,
            )
            bus_info = ""
            for line in info.stdout.splitlines():
                if line.startswith("bus-info:"):
                    bus_info = line.split(":", 1)[1].strip()
                    break
            print(f"  {iface}: {bus_info}")
        except subprocess.CalledProcessError:
            print(f"  {iface}: <unable to read bus-info>")
    sys.exit(1)


def initialize_robot(piper: C_PiperInterface):
    """Initializes the robot arm: enables motors, moves to initial pose."""
    piper.EnableArm(7)
    enable_fun(piper=piper)

    # Move to initial pose
    target_joint_angles = np.zeros(NUM_JOINTS)  # Return to zero angles

    # Convert to int and Send Motor signal
    joint_0 = round(target_joint_angles[0] * FACTOR)
    joint_1 = round(target_joint_angles[1] * FACTOR)
    joint_2 = round(target_joint_angles[2] * FACTOR)
    joint_3 = round(target_joint_angles[3] * FACTOR)
    joint_4 = round(target_joint_angles[4] * FACTOR)
    joint_5 = round((target_joint_angles[5]) * FACTOR)  # Joint Angle is not always = 0
    joint_6 = round(0.2 * 1000 * 1000)

    piper.MotionCtrl_2(0x01, 0x01, 80, 0x00)
    piper.JointCtrl(joint_0, joint_1, joint_2, joint_3, joint_4, joint_5)
    piper.GripperCtrl(abs(joint_6), 1000, 0x01, 0)
    time.sleep(0.5)  # Wait for the robot to reach the initial pose

    acc_limit = 500  # Define the acceleration limit
    piper.JointConfig(joint_num=7, set_zero=0, acc_param_is_effective=0xAE, max_joint_acc=acc_limit, clear_err=0xAE)
    
    time.sleep(0.5)


def load_pinocchio_model():
    """Loads the robot model using pinocchio."""
    pinocchio_model_dir = join(dirname(dirname(str(abspath(__file__)))), "meshcat")  # Adjust path as necessary
    model_path = pinocchio_model_dir
    mesh_dir = pinocchio_model_dir
    urdf_filename = "piper_B2.urdf"  # Use your robot's URDF
    urdf_model_path = join(join(model_path, "piper_description/urdf"), urdf_filename)
    model, collision_model, visual_model = pin.buildModelsFromUrdf(urdf_model_path, mesh_dir)
    data = model.createData()
    return model, collision_model, visual_model, data


def setup_meshcat_visualizer(model, collision_model, visual_model):
    """Initializes and sets up the Meshcat visualizer."""
    #viz = MeshcatVisualizer(model, collision_model, visual_model)
    viz = MeshcatVisualizer(model, collision_model, visual_model)
    try:
        viz.initViewer(open=True)
    except ImportError as err:
        print("Error while initializing the viewer. It seems you should install Python meshcat")
        print(err)
        sys.exit(0)
    viz.loadViewerModel()
    return viz


def move_to_initial_pose(piper):
    """Moves the robot to a predefined initial pose."""
    # target_joint_angles = [0.0, 0.992, -0.40, 0.0, -0.50, 0.0]
    #target_joint_angles = [0.0, 0.42, -0.35, 0.0, 0.01, 0.0]
    target_joint_angles = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    joint_0 = round(target_joint_angles[0] * FACTOR)
    joint_1 = round(target_joint_angles[1] * FACTOR)
    joint_2 = round(target_joint_angles[2] * FACTOR)
    joint_3 = round(target_joint_angles[3] * FACTOR)  # Force to 0
    joint_4 = round(target_joint_angles[4] * FACTOR)
    joint_5 = round((target_joint_angles[5]) * FACTOR)  # Force to 0
    joint_6 = round(0.2 * 1000 * 1000)

    piper.MotionCtrl_2(0x01, 0x01, 95, 0x00)
    piper.JointCtrl(joint_0, joint_1, joint_2, joint_3, joint_4, joint_5)
    piper.GripperCtrl(abs(joint_6), 1000, 0x01, 0)
    time.sleep(0.1)


def clamp(value, limits):
    """Clamp a value within the given limits."""
    lower, upper = limits
    return max(lower, min(value, upper))


def main():
    """Main control loop for the robot arm."""

    run_can_activation_script()

    mqtt_handler = MQTTHandler(MQTT_BROKER, MQTT_PORT)  # Use random client ID
    mqtt_handler.connect()

    piper = C_PiperInterface(CAN_IFACE)
    piper.ConnectPort()

    initialize_robot(piper)

    # Load Pinocchio model and setup Meshcat
    model, collision_model, visual_model, data = load_pinocchio_model()
    viz = setup_meshcat_visualizer(model, collision_model, visual_model)

    viz.display(np.zeros(model.nq))
    r = Rotation.from_euler('zx', [-140, 40], degrees=True)  # Rotate Z, then X. Order matters!
    rotation_matrix = r.as_matrix()

    # Create a translation vector (optional - adjust camera distance/position)
    translation_vector = np.array([1.5, 1.5, 1])  # move camera 3 units back on the Z axis

    # Combine rotation and translation into a SE3 transform
    camera_transform = pin.SE3(rotation_matrix, translation_vector)

    # Set the camera transform in Meshcat
    viz.viewer["/Cameras/default"].set_transform(camera_transform.homogeneous)

    # Initial pose and calibration
    current_end_pose = INITIAL_END_POSE[:]
    old_end_pose = INITIAL_END_POSE[:]
    calibration_pose = None
    last_joint_angles = np.zeros(4)  # Changed to reflect 4 active joints
    trigger_state = 0

    time.sleep(0.5)
    joint_0 = 0
    joint_1 = 0
    joint_2 = 0
    joint_4 = 0

    try:
        z = 0
        joint_0 = 0
        joint_1 = INITIAL_END_POSE[1] * FACTOR
        joint_2 = INITIAL_END_POSE[2] * FACTOR
        joint_4 = 0
        while True:
            # Get data from MQTT
            (
                endpose_data,
                trigger,
                joystickX,
                joystickY,
                joystickClick,
                buttonA,
                buttonB,
                grip,
                temp,
                message_available,
            ) = mqtt_handler.get_data()

            # Reset condition
            if temp == 1:
                #logging.info("Resetting to initial position due to temp = 1")
                viz.display(np.zeros(model.nq))
                #viz.display(np.zeros(8))
                move_to_initial_pose(piper)
                current_end_pose = INITIAL_END_POSE[:]
                old_end_pose = INITIAL_END_POSE[:]
                calibration_pose = None
                last_joint_angles = np.zeros(4)
                joint_0 = 0
                joint_1 = 0
                joint_2 = 0
                joint_4 = 0

                z = 0.015
                time.sleep(0.1)  # Give the robot some time to move

            # Process button A and B presses
            if buttonA == 1:
                #logging.info("Switch to PICO mode")
                move_to_initial_pose(piper)
                current_end_pose = INITIAL_END_POSE[:]
                old_end_pose = INITIAL_END_POSE[:]
                calibration_pose = None
                last_joint_angles = np.zeros(4)
                time.sleep(1)
                mqtt_handler.switch_control_mode("pico")

            elif buttonB == 1:
                #logging.info("Switch to WEB mode")
                move_to_initial_pose(piper)
                current_end_pose = [0.1, 0, 0.3, 0, pi / 2, 0]
                # current_end_pose = INITIAL_END_POSE[:]
                old_end_pose = INITIAL_END_POSE[:]
                calibration_pose = None
                last_joint_angles = np.zeros(4)
                endpose_data = [0, 0, 0, 0, 0, 0]
                time.sleep(1)
                mqtt_handler.switch_control_mode("web")

            if message_available:  # Only process if a message has arrived
                if mqtt_handler.control_mode == "pico":
                    endpose = endpose_data

                    if (
                        endpose is not None and trigger is not None
                    ):  # Verify we have valid endpose data from process_message
                        try:
                            endpose = [float(x) for x in endpose]
                            trigger = int(trigger)

                            if len(endpose) != 6:
                                #logging.warning(f"Error: Incorrect endpose length ({len(endpose)}), expected 6.")
                                continue

                        except (ValueError, TypeError) as e:
                            #logging.error(f"Error unpacking MQTT: {e}")
                            continue

                        # Handle trigger state
                        if trigger == 0:  # Trigger Released
                            if trigger_state == 1:
                                #logging.info("Trigger released. Returning to initial pose...")
                                move_to_initial_pose(piper)

                                current_end_pose = INITIAL_END_POSE[:]
                                old_end_pose = INITIAL_END_POSE[:]
                                calibration_pose = None
                            trigger_state = 0

                        elif trigger == 1:  # Trigger Pressed
                            trigger_state = 1

                            # Calibrate on first trigger press
                            if calibration_pose is None:
                                calibration_pose = endpose[:]
                                #logging.info("Trigger pressed. Calibrating to current pose as zero point...")

                            # Calculate deltas from calibrated pose
                            delta_x = endpose[0] - calibration_pose[0]
                            delta_y = endpose[1] - calibration_pose[1]
                            delta_z = endpose[2] - calibration_pose[2]
                            delta_rx = endpose[3] - calibration_pose[3]
                            delta_ry = endpose[4] - calibration_pose[4]
                            delta_rz = endpose[5] - calibration_pose[5]

                            if delta_z < -0.1:
                                delta_z = -0.1

                            new_end_pose = [
                                INITIAL_END_POSE[0] + delta_x,
                                INITIAL_END_POSE[1] + delta_y,
                                INITIAL_END_POSE[2] + delta_z,
                                INITIAL_END_POSE[3] + delta_rx,
                                INITIAL_END_POSE[4] + delta_ry,
                                INITIAL_END_POSE[5] + delta_rz,
                            ]

                            current_end_pose = new_end_pose[:]

                            # IK to find the joint angles, send angles to robot directly
                            target_pose = np.eye(4)
                            target_pose[:3, :3] = Rotation.from_euler("xyz", current_end_pose[3:]).as_matrix()
                            target_pose[:3, 3] = current_end_pose[:3]

                            joint_angles, success, elapsed_time = inverse_kinematics(
                                model, data, target_pose, last_joint_angles
                            )

                            if success:
                                last_joint_angles = joint_angles

                                # Convert to int and Send Motor signal
                                joint_0 = round(joint_angles[0] * FACTOR)
                                joint_1 = round(joint_angles[1] * FACTOR)
                                joint_2 = round(joint_angles[2] * FACTOR)
                                joint_3 = round(0 * FACTOR)  # Fixed Joint 3
                                joint_4 = round(joint_angles[3] * FACTOR)  # Joint 4 from result.x (remember, q_init is now 4 elements)
                                joint_5 = round(0 * FACTOR)  # Fixed Joint 5
                                joint_6 = round((1 - grip) / 5 * 1000 * 1000)

                                # Visualize the robot in Meshcat
                                joint_angles_full = np.zeros(model.nq)
                                joint_angles_full[12] = joint_angles[0]
                                joint_angles_full[13] = joint_angles[1]
                                joint_angles_full[14] = joint_angles[2]
                                joint_angles_full[15] = 0  # Fixed
                                joint_angles_full[16] = joint_angles[3]
                                joint_angles_full[17] = 0  # Fixed

                                viz.display(joint_angles_full)

                                piper.MotionCtrl_2(0x01, 0x01, 90, 0x00)
                                piper.JointCtrl(joint_0, joint_1, joint_2, joint_3, joint_4, joint_5)
                                piper.GripperCtrl(abs(joint_6), 1000, 0x01, 0)

                            #else:
                                #logging.warning(f"IK Failed")
                            old_end_pose = current_end_pose[:]

                elif mqtt_handler.control_mode == "web":
                    endpose_delta = endpose_data
                    # print(endpose_delta)
                    # REMOVED BUTTON A AND BUTTON B CONTROL

                    if endpose_delta is not None:
                        try:
                            endpose_delta = [float(x) for x in endpose_delta]

                            if len(endpose_delta) != 6:
                                print(f"Error: Incorrect endpose length ({len(endpose_delta)}), expected 6.")
                                continue

                        except (ValueError, TypeError) as e:
                            print(f"Error unpacking MQTT: {e}")
                            continue

                        # Accumulate the delta values to the current end pose
                        new_end_pose = [current_end_pose[i] + endpose_delta[i] for i in range(6)]

                        current_end_pose = new_end_pose[:]

                        # Direct Joint Control based on Z-axis rotation
                        z_rotation_delta = endpose_delta[5]
                        z_delta = endpose_delta[2]
                        z += z_delta
                        #print("z",z)
                        if z > 0.57:
                            z = 0.57
                        if z < 0.001:
                            z = 0.001
                        joint_0 += z_rotation_delta # Map z-axis rotation to joint0
                        joint_1 =  z * 2
                        joint_2 = -z * 4
                        joint_4 =  z * 2

                        # Convert to int and Send Motor signal
                        joint_0_send = round(joint_0* FACTOR)
                        joint_1_send = round(joint_1* FACTOR) 
                        joint_2_send = round(joint_2* FACTOR)  
                        joint_3_send = 0 #  fixed
                        joint_4_send = round(joint_4* FACTOR)
                        joint_5_send = 0  # fixed

                        # Visualize the robot in Meshcat
                        joint_angles_full = np.zeros(model.nq)
                        joint_angles_full[12] = joint_0
                        joint_angles_full[13] = joint_1
                        joint_angles_full[14] = joint_2
                        joint_angles_full[15] = 0  # Fixed
                        joint_angles_full[16] = joint_4
                        joint_angles_full[17] = 0  # Fixed

                        viz.display(joint_angles_full)

                        piper.MotionCtrl_2(0x01, 0x01, 90, 0x00)
                        piper.JointCtrl(joint_0_send, joint_1_send, joint_2_send, joint_3_send, joint_4_send, joint_5_send)



            time.sleep(0.001)  

    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        mqtt_handler.disconnect()
        piper.DisconnectPort()


if __name__ == "__main__":
    main()

#!/usr/bin/env python
import rospy
from duckietown_msgs.msg import FSMState, BoolStamped, Twist2DStamped, LanePose, StopLineReading
from std_srvs.srv import EmptyRequest, EmptyResponse, Empty
from std_msgs.msg import String, Int16 #Imports msg
import copy

class OpenLoopIntersectionNode(object):
    def __init__(self):
        # Save the name of the node
        self.node_name = rospy.get_name()
        self.mode = None
        self.turn_type = -1
        self.in_lane = False
        self.isProcessedTurn = False
        self.lane_pose = LanePose()
        self.stop_line_reading = StopLineReading()

        self.trajectory_reparam = rospy.get_param("~trajectory_reparam",1)
        self.pub_cmd = rospy.Publisher("~car_cmd",Twist2DStamped,queue_size=1)
        self.pub_done = rospy.Publisher("~intersection_done",BoolStamped,queue_size=1)

        # Construct originalManeuvers
        self.originalManeuvers = dict()

        self.originalManeuvers[0] = self.getManeuver("turn_left")
        self.originalManeuvers[1] = self.getManeuver("turn_forward")
        self.originalManeuvers[2] = self.getManeuver("turn_right")
        # self.originalManeuvers[-1] = self.getManeuver("turn_stop")
        self.maneuvers = copy.deepcopy(self.originalManeuvers)

        self.srv_turn_left = rospy.Service("~turn_left", Empty, self.cbSrvLeft)
        self.srv_turn_right = rospy.Service("~turn_right", Empty, self.cbSrvRight)
        self.srv_turn_forward = rospy.Service("~turn_forward", Empty, self.cbSrvForward)

        self.srv_turn_left_test = rospy.Service("~turn_left_test", Empty, self.cbSrvLeftTest)
        self.srv_turn_right_test = rospy.Service("~turn_right_test", Empty, self.cbSrvRightTest)
        self.srv_turn_forward_test = rospy.Service("~turn_forward_test", Empty, self.cbSrvForwardTest)


        self.rate = rospy.Rate(30)

        # Subscribers
        self.sub_in_lane = rospy.Subscriber("~in_lane", BoolStamped, self.cbInLane, queue_size=1)
        self.sub_turn_type = rospy.Subscriber("~turn_type", Int16, self.cbTurnType, queue_size=1)
        self.sub_mode = rospy.Subscriber("~mode", FSMState, self.cbFSMState, queue_size=1)
        self.sub_lane_pose = rospy.Subscriber("~lane_pose", LanePose, self.cbLanePose, queue_size=1)
        self.sub_stop_line = rospy.Subscriber("~stop_line_reading", StopLineReading, self.cbStopLine, queue_size=1)

    def cbSrvLeft(self,req):
        self.trigger(0)
        return EmptyResponse()

    def cbSrvForward(self,req):
        self.trigger(1)
        return EmptyResponse()

    def cbSrvRight(self,req):
        self.trigger(2)
        return EmptyResponse()

    def cbSrvLeftTest(self,req):
        self.trigger_test(0)
        return EmptyResponse()

    def cbSrvForwardTest(self,req):
        self.trigger_test(1)
        return EmptyResponse()

    def cbSrvRightTest(self,req):
        self.trigger_test(2)
        return EmptyResponse()

    def getManeuver(self,param_name):
        param_list = rospy.get_param("~%s"%(param_name))
        # rospy.loginfo("PARAM_LIST:%s" %param_list)
        maneuver = list()
        for param in param_list:
            maneuver.append((param[0],Twist2DStamped(v=param[1],omega=param[2])))
        # rospy.loginfo("MANEUVER:%s" %maneuver)
        return maneuver

    def cbTurnType(self,msg):
        if self.mode == "INTERSECTION_CONTROL":
            self.turn_type = msg.data #Only listen if in INTERSECTION_CONTROL mode
            self.trigger(self.turn_type)

    def cbLanePose(self,msg):
        self.lane_pose = msg

    def cbStopLine(self,msg):
        rospy.loginfo("[%s] cbStopLine: %s" %(self.node_name, msg.line_angle))
        self.stop_line_reading = msg

        # TODO remove in lane it is now handled by the logic_gate_node
    def cbInLane(self,msg):
        self.in_lane = msg.data

    def cbFSMState(self,msg):
        if (not self.mode == "INTERSECTION_CONTROL") and msg.state == "INTERSECTION_CONTROL":
            # Switch into INTERSECTION_CONTROL mode
            rospy.loginfo("[%s] %s triggered." %(self.node_name,self.mode))
            self.isProcessedTurn = False
            start = rospy.Time.now()
            current = rospy.Time.now()
            while current.secs - start.secs < 0.5:
                current = rospy.Time.now()
                self.trigger(-1)
        self.mode = msg.state
        self.turn_type = -1 #Reset turn_type at mode change

    def publishDoneMsg(self):
        msg = BoolStamped()
        msg.header.stamp = rospy.Time.now()
        msg.data = True
        self.pub_done.publish(msg)
        self.isProcessedTurn = True
        rospy.loginfo("[%s] interesction_done!" %(self.node_name))

    def update_trajectory(self,turn_type):
        rospy.loginfo("updating trajectory: distance from stop_line=%s, lane_pose_phi = %s, stop_line_phi = %s", self.stop_line_reading.stop_line_point.x,  self.lane_pose.phi, self.stop_line_reading.line_angle)
        (self.maneuvers[turn_type]).pop(0)
        first_leg = self.originalManeuvers[turn_type][0]
        exec_time = first_leg[0];
        car_cmd   = first_leg[1];
        new_exec_time = exec_time + self.stop_line_reading.stop_line_point.x/car_cmd.v
        rospy.loginfo("old exec_time = %s, new_exec_time = %s" ,exec_time, new_exec_time)
        #new_car_cmd = Twist2DStamped(v=car_cmd.v,omega=(car_cmd.omega - self.lane_pose.phi/new_exec_time))
        # minus (-self.stop_line_reading.line_angle) because need to use bot angle in lane instead stop-line angle
        new_car_cmd = Twist2DStamped(v=car_cmd.v,omega=(car_cmd.omega - (-self.stop_line_reading.line_angle * 2)/new_exec_time))
        new_first_leg = [new_exec_time,new_car_cmd]
        rospy.loginfo("old car command: %s (omega=%s)", str(car_cmd), car_cmd.omega )
        rospy.loginfo("new car command: %s (omega=%s)", str(new_car_cmd), new_car_cmd.omega)
        self.maneuvers[turn_type].insert(0,new_first_leg)

    def trigger(self,turn_type):
        if turn_type == -1: #Wait. Publish stop command. Does not publish done.
            cmd = Twist2DStamped(v=0.0,omega=0.0)
            cmd.header.stamp = rospy.Time.now()
            self.pub_cmd.publish(cmd)
            return

        if self.isProcessedTurn:
            return

        if (self.trajectory_reparam):
            self.update_trajectory(turn_type)

        published_already = False
        for index, pair in enumerate(self.maneuvers[turn_type]):
            rospy.loginfo("[%s] drive %s sec, cmd = %s", self.node_name, pair[0], pair[1])
            cmd = copy.deepcopy(pair[1])
            start_time = rospy.Time.now()
            end_time = start_time + rospy.Duration.from_sec(pair[0])
            while rospy.Time.now() < end_time:
                if not self.mode == "INTERSECTION_CONTROL": # If not in the mode anymore, return
                    return
                rospy.loginfo("[%s] publishing cmd = %s", self.node_name, pair[1])
                cmd.header.stamp = rospy.Time.now()
                self.pub_cmd.publish(cmd)
                if index > 2:
                    # See if need to publish interesction_done
                    if self.in_lane and not (published_already):
                        rospy.loginfo("[%s] self.in_lane==true, returning from function trigger" %(self.node_name))
                        published_already = True
                        self.publishDoneMsg()
                        return
                self.rate.sleep()
        # Done with the sequence
        if not published_already:
            self.publishDoneMsg()

    def trigger_test(self,turn_type):
        for index, pair in enumerate(self.maneuvers[turn_type]):
            rospy.loginfo("[%s] drive %s sec", self.node_name, pair[0])
            cmd = copy.deepcopy(pair[1])
            start_time = rospy.Time.now()
            end_time = start_time + rospy.Duration.from_sec(pair[0])
            while rospy.Time.now() < end_time:
                cmd.header.stamp = rospy.Time.now()
                self.pub_cmd.publish(cmd)
                self.rate.sleep()
        cmd = Twist2DStamped(v=0.0,omega=0.0)
        cmd.header.stamp = rospy.Time.now()
        self.pub_cmd.publish(cmd)

    def on_shutdown(self):
        rospy.loginfo("[%s] Shutting down." %(self.node_name))

if __name__ == '__main__':
    # Initialize the node with rospy
    rospy.init_node('open_loop_intersection_node', anonymous=False)

    # Create the NodeName object
    node = OpenLoopIntersectionNode()

    # Setup proper shutdown behavior
    rospy.on_shutdown(node.on_shutdown)
    # Keep it spinning to keep the node alive
    rospy.spin()

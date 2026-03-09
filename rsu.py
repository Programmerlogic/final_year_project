import math
import time

class RSU:
    def __init__(self, node, network, radius=100):
        self.node = node
        self.network = network
        self.radius = radius

        # ---- Alert cooldown (seconds between repeated alerts to server) ----
        self.alert_cooldown = 5.0
        self._last_alert_time = 0.0

        # ---- V2I layer ----
        self.registered_vehicles = {}   # vid → latest telemetry
        self.vehicle_objects = {}       # vid → Vehicle object

        # ---- Long Wait Aggregation ----
        self.long_wait_buffer = {}      # vid → last_wait_duration
        self.last_batch_alert_time = 0.0
        self.batch_window = 10.0
        self.batch_threshold = 5
        self.is_congested = False
        self.signal = None 

    def get_position(self):
        return self.network.positions[self.node]

    def register_vehicle(self, vehicle):
        self.vehicle_objects[vehicle.id] = vehicle

    def remove_vehicle(self, vehicle):
        self.registered_vehicles.pop(vehicle.id, None)
        self.vehicle_objects.pop(vehicle.id, None)

    def receive_telemetry(self, vehicle, telemetry):
        self.registered_vehicles[vehicle.id] = telemetry

    def receive_long_wait_notification(self, vehicle, wait_duration):
        """Buffer a long wait notification from a vehicle."""
        self.long_wait_buffer[vehicle.id] = wait_duration

    def get_next_hop(self, destination, globally_congested=None):
        """
        RSU Instruction Brain:
        Computes the best next node for a vehicle to take to reach its destination,
        considering both local and global congestion.
        """
        if self.node == destination:
            return None

        try:
            path = self.network.dynamic_shortest_path(
                self.node,
                destination,
                globally_congested=globally_congested
            )

            if len(path) > 1:
                return path[1]

        except:
            pass

        return None

    def check_long_wait_batch(self, client=None):
        """
        Periodically check the buffer and send an aggregated alert if enough
        vehicles have reported a long wait.
        """
        if client is None or not client.is_connected:
            return

        now = time.time()
        # Rate limit the batch checks
        if now - self.last_batch_alert_time < 2.0:
            return

        buffer_count = len(self.long_wait_buffer)

        # ---- 1. AGGREGATE ALERT ----
        if buffer_count >= self.batch_threshold:
            avg_wait = sum(self.long_wait_buffer.values()) / buffer_count
            
            # Send aggregated alert to server
            client.send_junction_congestion_alert(
                self.node, 
                buffer_count, 
                round(avg_wait, 1)
            )
            
            # Reset buffer and timer
            self.long_wait_buffer.clear()
            self.last_batch_alert_time = now
            self.is_congested = True

        # ---- 2. CLEARANCE DETECTION ----
        elif self.is_congested:
            telemetry_list = list(self.registered_vehicles.values())
            num_vehicles = len(telemetry_list)

            # # A: If junction is completely empty, it's definitely clear
            # if num_vehicles == 0:
            #     client.send_junction_clear_alert(self.node)
            #     self.is_congested = False
            #     self.long_wait_buffer.clear()
            #     return

            # B: Calculate the current stationary queue
            current_queue = sum(1 for t in telemetry_list if t["speed"] < 0.001)
            avg_speed = sum(t["speed"] for t in telemetry_list) / num_vehicles

            # NEW LOGIC: Only clear if Light is GREEN AND Queue has shrunk significantly
            clearance_threshold = 3

            if current_queue <= clearance_threshold and avg_speed > 0.005:
                client.send_junction_clear_alert(self.node)
                self.is_congested = False
                self.long_wait_buffer.clear() # Wipe the buffer once cleared
                self.last_batch_alert_time = now

        # Cleanup old buffer entries periodically
        if now - self.last_batch_alert_time > self.batch_window:
             self.long_wait_buffer.clear()
             self.last_batch_alert_time = now



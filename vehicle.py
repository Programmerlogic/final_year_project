import pygame
import math
import random

VEHICLE_RADIUS = 6
NODE_RADIUS = 20


class OBU:
    """On-Board Unit — transmits telemetry to RSU."""
    def __init__(self, vehicle):
        self.vehicle = vehicle
        self.connected_rsu = None

    def get_telemetry(self):
        """Compute and return current telemetry packet."""
        v = self.vehicle

        if v.target_node is None:
            return None

        start_pos = v.network.positions[v.current_node]
        end_pos = v.network.positions[v.target_node]

        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        length = math.hypot(dx, dy)

        if length == 0:
            return None

        # GPS position
        gps_x = start_pos[0] + dx * v.progress
        gps_y = start_pos[1] + dy * v.progress

        # Heading (angle in degrees)
        heading = math.degrees(math.atan2(dy, dx))

        # Acceleration (speed change since last frame)
        acceleration = v.current_speed - v.prev_speed

        # Local vehicle density (vehicles within 150 units)
        nearby = 0
        for other in v.network.vehicles:
            if other is v or other.target_node is None:
                continue
            o_start = other.network.positions[other.current_node]
            o_end = other.network.positions[other.target_node]
            odx = o_end[0] - o_start[0]
            ody = o_end[1] - o_start[1]
            ox = o_start[0] + odx * other.progress
            oy = o_start[1] + ody * other.progress
            if math.hypot(ox - gps_x, oy - gps_y) <= 150:
                nearby += 1

        return {
            "vehicle_id": v.id,
            "gps": (gps_x, gps_y),
            "speed": v.current_speed,
            "heading": heading,
            "acceleration": acceleration,
            "density_estimate": nearby
        }

    def get_signal_strength(self, rsu):
        """Signal strength = inverse of distance to RSU (0 if out of range)."""
        telemetry = self.get_telemetry()
        if telemetry is None:
            return 0

        gps_x, gps_y = telemetry["gps"]
        rsu_x, rsu_y = rsu.get_position()
        dist = math.hypot(gps_x - rsu_x, gps_y - rsu_y)

        if dist > rsu.radius:
            return 0

        return 1 / (dist + 1e-6)  # stronger when closer

    def handover(self, rsus):
        """Switch to RSU with strongest signal if better than current."""
        best_rsu = None
        best_strength = 0

        for rsu in rsus:
            strength = self.get_signal_strength(rsu)
            if strength > best_strength:
                best_strength = strength
                best_rsu = rsu

        # Handover if new RSU is better
        if best_rsu is not self.connected_rsu:
            if self.connected_rsu is not None:
                self.connected_rsu.remove_vehicle(self.vehicle)
            self.connected_rsu = best_rsu
            if best_rsu is not None:
                best_rsu.register_vehicle(self.vehicle)

    def transmit(self):
        """Send telemetry to connected RSU."""
        if self.connected_rsu is None:
            return
        telemetry = self.get_telemetry()
        if telemetry:
            self.connected_rsu.receive_telemetry(self.vehicle, telemetry)

    def send_long_wait_notification(self, wait_duration):
        """Notify the RSU that the vehicle has been stuck."""
        if self.connected_rsu is None:
            return
        
        # We don't send the full telemetry again, just the wait info
        self.connected_rsu.receive_long_wait_notification(self.vehicle, wait_duration)


class Vehicle:
    def __init__(self, vid, network, start, destination):
        self.id = vid
        self.network = network
        self.current_node = start
        self.destination = destination
        
        # In the "RSU Instruction" model, the vehicle doesn't have a route.
        # It just knows which node it is driving towards.
        self.target_node = None 
        self.progress = 0

        # Standardized speed for more predictable flow
        self.base_speed = random.uniform(0.002, 0.004)
        self.current_speed = self.base_speed
        self.prev_speed = self.base_speed

        self.color = (0, 0, 255)
        self.obu = OBU(self)

        # ---- Enhanced Wait Tracking ----
        self.wait_time = 0
        self.move_time = 0                 # frames spent moving "fast"
        self.next_notify_threshold = 200   # start with 5s at 40FPS
        self.max_notify_threshold = 2400   # cap at 1 minute

    def update(self, signals, vehicles, rsus=None, globally_congested=None):
        # Initial instruction if we don't have a target yet
        rsus = rsus or []
        if self.target_node is None:
            if self.current_node == self.destination:
                return # Arrived
                
            # ── RSU NAVIGATION HELP ──
            # rsu = next((r for r in rsus if r.node == self.current_node), None)
            rsu = None
            if rsus:
                rsu = next((r for r in rsus if r.node == self.current_node), None)
            if rsu:
                self.target_node = rsu.get_next_hop(self.destination, globally_congested)
            else:
                # Fallback to direct shortest path if no RSU is present
                try:
                    path = self.network.dynamic_shortest_path(self.current_node, self.destination, globally_congested)
                    if len(path) > 1:
                        self.target_node = path[1]
                except:
                    pass
        
        if self.target_node is None:
            return

        speed = self.base_speed
        self.prev_speed = self.current_speed

        # ---- TRAFFIC SIGNAL CHECK ----
        for signal in signals:
            if signal.node == self.target_node:
                lane_state = signal.state.get((self.current_node, self.target_node), "GREEN")
                if lane_state in ["RED", "YELLOW"]:
                    start_pos = self.network.positions[self.current_node]
                    end_pos = self.network.positions[self.target_node]
                    dx = end_pos[0] - start_pos[0]
                    dy = end_pos[1] - start_pos[1]
                    length = math.hypot(dx, dy)
                    if length == 0:
                        continue
                    stop_distance = NODE_RADIUS + 10
                    stop_progress = 1 - (stop_distance / length)
                    if self.progress >= stop_progress:
                        speed = 0

        # ---- PREVENT OVERLAPPING (QUEUE MODEL) ----
        for other in vehicles:
            if other is self:
                continue
            if (other.current_node == self.current_node and
                    other.target_node == self.target_node):
                if other.progress > self.progress:
                    gap = other.progress - self.progress
                    # Scaled gap check for realistic spacing
                    if gap < 0.03: 
                        speed = 0

        # ---- WAIT TRACKING LOGIC ----
        if speed < 0.001:  # "Slow-moving" threshold
            self.wait_time += 1
            self.move_time = 0
        else:
            self.move_time += 1
            # Persistence: Only reset wait_time if moving for > 2 seconds
            if self.move_time > 80:
                self.wait_time = 0
                self.next_notify_threshold = 200 # reset backoff

        # ---- LONG WAIT NOTIFICATION (Exponential Backoff) ----
        if self.wait_time >= self.next_notify_threshold:
            self.obu.send_long_wait_notification(self.wait_time)
            # Increase next threshold (exponentially)
            self.next_notify_threshold = min(
                int(self.next_notify_threshold * 1.5), 
                self.max_notify_threshold
            )

        self.current_speed = speed

        # ---- OBU: HANDOVER + TRANSMIT ----
        if rsus:
            self.obu.handover(rsus)
            self.obu.transmit()

        self.progress += speed

        if self.progress >= 1:
            # We just reached 'target_node'
            self.current_node = self.target_node
            self.progress = 0
            
            if self.current_node == self.destination:
                self.target_node = None
                return

            # Request next instruction from the RSU at the new node
            rsu = next((r for r in rsus if r.node == self.current_node), None)
            if rsu:
                self.target_node = rsu.get_next_hop(self.destination, globally_congested)
            else:
                # Fallback to direct shortest path
                try:
                    path = self.network.dynamic_shortest_path(self.current_node, self.destination, globally_congested)
                    if len(path) > 1:
                        self.target_node = path[1]
                    else:
                        self.target_node = None
                except:
                    self.target_node = None

            if self.target_node:
                self.network.increase_traffic(self.current_node, self.target_node)

    def draw(self, screen, zoom, offset_x, offset_y):

        if self.target_node is None:
            return

        start_pos = self.network.positions[self.current_node]
        end_pos = self.network.positions[self.target_node]

        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]

        length = math.hypot(dx, dy)

        if length == 0:
            return

        lane_offset_x = -dy / length * 5
        lane_offset_y = dx / length * 5

        x = start_pos[0] + dx * self.progress + lane_offset_x
        y = start_pos[1] + dy * self.progress + lane_offset_y

        screen_x = x * zoom + offset_x
        screen_y = y * zoom + offset_y

        angle = math.atan2(dy, dx)

        size = 8 * zoom

        front = (
            screen_x + math.cos(angle) * size,
            screen_y + math.sin(angle) * size
        )

        left = (
            screen_x + math.cos(angle + 2.5) * size,
            screen_y + math.sin(angle + 2.5) * size
        )

        right = (
            screen_x + math.cos(angle - 2.5) * size,
            screen_y + math.sin(angle - 2.5) * size
        )

        if self.obu.connected_rsu:
            color = (0, 200, 0)
        else:
            color = (200, 0, 0)

        pygame.draw.polygon(screen, color, [front, left, right])
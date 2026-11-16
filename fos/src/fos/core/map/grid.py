"""
Grid map classes for spatial simulation scenes.

Provides a sparse-tile grid with named locations, A* pathfinding, and
serialization. Extracted from the legacy VillageScene; display/render
methods that depend on the legacy Agent class are intentionally omitted.

Contains: MapLocation, Tile, GameMap
"""
import heapq
import math
from typing import Dict, Iterable, List, Optional, Tuple


class MapLocation:
    """A named point of interest on the game map."""

    def __init__(
        self,
        name: str,
        x: int,
        y: int,
        location_type: str = "generic",
        description: str = "",
        resources: Dict = None,
        capacity: int = -1,
    ):
        self.name = name
        self.x = x
        self.y = y
        self.location_type = location_type  # "building", "resource", "landmark", "generic"
        self.description = description
        self.resources = resources or {}
        self.capacity = capacity  # -1 = unlimited
        self.agents_here: set = set()

    def add_agent(self, agent_name: str) -> bool:
        """Add an agent to this location, respecting capacity. Returns True if added."""
        if self.capacity == -1 or len(self.agents_here) < self.capacity:
            self.agents_here.add(agent_name)
            return True
        return False

    def remove_agent(self, agent_name: str):
        """Remove an agent from this location."""
        self.agents_here.discard(agent_name)

    def get_distance_to(self, other_x: int, other_y: int) -> float:
        """Euclidean distance to another coordinate."""
        return math.sqrt((self.x - other_x) ** 2 + (self.y - other_y) ** 2)


class Tile:
    """A single grid cell with terrain and traversal properties."""

    def __init__(
        self,
        passable: bool = True,
        movement_cost: int = 1,
        terrain: str = "plain",
        resources: Optional[Dict] = None,
    ):
        self.passable = passable
        self.movement_cost = movement_cost
        self.terrain = terrain
        self.resources = resources or {}

    def serialize(self) -> dict:
        return {
            "passable": self.passable,
            "movement_cost": self.movement_cost,
            "terrain": self.terrain,
            "resources": self.resources,
        }

    @classmethod
    def deserialize(cls, data: Dict) -> "Tile":
        return cls(
            passable=data.get("passable", True),
            movement_cost=data.get("movement_cost", 1),
            terrain=data.get("terrain", "plain"),
            resources=data.get("resources", {}),
        )


class GameMap:
    """Grid-based map with named locations, sparse tile overrides, and A* pathfinding."""

    def __init__(self, width: int = 20, height: int = 20):
        self.width = width
        self.height = height
        self.locations: Dict[str, MapLocation] = {}
        self.grid: Dict[Tuple[int, int], str] = {}   # (x, y) -> location name
        self.tiles: Dict[Tuple[int, int], Tile] = {}  # sparse; only non-default tiles

    def serialize(self) -> dict:
        tiles = []
        for (x, y), tile in self.tiles.items():
            tiles.append({"x": x, "y": y, **tile.serialize()})
        return {
            "width": self.width,
            "height": self.height,
            "tiles": tiles,
            "locations": [
                {
                    "name": loc.name,
                    "x": loc.x,
                    "y": loc.y,
                    "type": loc.location_type,
                    "description": loc.description,
                    "resources": loc.resources,
                    "capacity": loc.capacity,
                }
                for loc in self.locations.values()
            ],
        }

    @classmethod
    def deserialize(cls, data: Dict) -> "GameMap":
        """Create a GameMap from a serialized dict. Returns an empty map if data is empty."""
        if not data:
            return cls()
        width = data.get("width", 20)
        height = data.get("height", 20)
        game_map = cls(width, height)

        for t in data.get("tiles", []):
            x, y = t["x"], t["y"]
            game_map.tiles[(x, y)] = Tile.deserialize(t)

        for loc in data.get("locations", []):
            game_map.add_location(
                loc.get("name"),
                loc.get("x"),
                loc.get("y"),
                location_type=loc.get("type", "generic"),
                description=loc.get("description", ""),
                resources=loc.get("resources", {}),
                capacity=loc.get("capacity", -1),
            )
        return game_map

    def add_location(
        self,
        name: str,
        x: int,
        y: int,
        location_type: str = "generic",
        description: str = "",
        resources: Dict = None,
        capacity: int = -1,
    ) -> bool:
        """Add a named location at (x, y). Returns False if coordinates are out of bounds."""
        if 0 <= x < self.width and 0 <= y < self.height:
            location = MapLocation(name, x, y, location_type, description, resources, capacity)
            self.locations[name] = location
            self.grid[(x, y)] = name
            return True
        return False

    def get_location(self, name: str) -> Optional[MapLocation]:
        """Return the named location, or None if not found."""
        return self.locations.get(name)

    def get_location_at(self, x: int, y: int) -> Optional[MapLocation]:
        """Return the location at coordinate (x, y), or None if no location there."""
        location_name = self.grid.get((x, y))
        return self.locations.get(location_name) if location_name else None

    def get_all_locations(self) -> List[MapLocation]:
        """Return all registered locations."""
        return list(self.locations.values())

    def get_nearby_locations(self, x: int, y: int, radius: int = 3) -> List[MapLocation]:
        """Return locations within Manhattan distance radius, sorted by distance."""
        nearby = [
            loc for loc in sorted(
                self.locations.values(), key=lambda location: (location.y, location.x, location.name)
            )
            if abs(loc.x - x) + abs(loc.y - y) <= radius
        ]
        return sorted(nearby, key=lambda loc: abs(loc.x - x) + abs(loc.y - y))

    def get_tile(self, x: int, y: int) -> Tile:
        """Return the tile at (x, y), defaulting to a passable plain tile."""
        return self.tiles.get((x, y), Tile())

    def in_bounds(self, x: int, y: int) -> bool:
        """Return True if (x, y) is within the map boundaries."""
        return 0 <= x < self.width and 0 <= y < self.height

    def is_passable(self, x: int, y: int) -> bool:
        """Return True if (x, y) is in bounds and its tile is passable."""
        return self.in_bounds(x, y) and self.get_tile(x, y).passable

    def neighbors(self, x: int, y: int) -> Iterable[Tuple[int, int]]:
        """Yield 4-directional (von Neumann) passable neighbor coordinates."""
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.is_passable(nx, ny):
                yield nx, ny

    def heuristic(self, a: Tuple[int, int], b: Tuple[int, int]) -> float:
        """Manhattan distance heuristic for A*."""
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def find_path(
        self, start: Tuple[int, int], goal: Tuple[int, int]
    ) -> Optional[List[Tuple[int, int]]]:
        """A* pathfinding from start to goal. Returns path including goal, or None if unreachable."""
        if start == goal:
            return [goal]
        if not (self.is_passable(*start) and self.is_passable(*goal)):
            return None

        open_heap: List[Tuple[float, Tuple[int, int]]] = []
        heapq.heappush(open_heap, (0, start))
        came_from: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}
        g_score: Dict[Tuple[int, int], float] = {start: 0}

        while open_heap:
            _, current = heapq.heappop(open_heap)
            if current == goal:
                path = []
                while current is not None:
                    path.append(current)
                    current = came_from[current]
                path.reverse()
                return path

            cx, cy = current
            for nx, ny in self.neighbors(cx, cy):
                tentative_g = g_score[current] + self.get_tile(nx, ny).movement_cost
                neighbor = (nx, ny)
                if tentative_g < g_score.get(neighbor, float("inf")):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score = tentative_g + self.heuristic(neighbor, goal)
                    heapq.heappush(open_heap, (f_score, neighbor))

        return None

    def path_cost(self, path: List[Tuple[int, int]]) -> int:
        """Sum of movement costs for each step in the path (excludes the start tile)."""
        if not path:
            return 0
        cost = 0
        for x, y in path[1:]:
            cost += max(1, int(self.get_tile(x, y).movement_cost))
        return cost

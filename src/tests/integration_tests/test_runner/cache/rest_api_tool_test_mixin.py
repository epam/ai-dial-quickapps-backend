import json

from fastapi import Request, Response


class RestApiToolTestMixin:
    def __init__(self, *args, **kwargs):
        self._box_for_shapes: _BoxForShapes | None = None
        super().__init__(*args, **kwargs)

    async def rest_test_get(self, request: Request):
        if self._box_for_shapes is None:
            return Response(content="The box not created", status_code=404)
        query = request.query_params.get("shape")
        found = next(
            (
                item
                for item in self._box_for_shapes.get_shapes()
                if str(query).lower() in str(item).lower()
            ),
            None,
        )
        return Response(
            content="Shape is not in the box" if not found else str(found), media_type="text/plain"
        )

    async def rest_test_post(self, request: Request):
        body = await request.body()
        try:
            data = json.loads(body)
            inner = data.get("box_data", {})
            inner = json.loads(inner)
            capacity = inner.get("capacity")
            shapes = inner.get("shapes", [])
            if isinstance(capacity, int) and isinstance(shapes, list):
                self._box_for_shapes = _BoxForShapes(capacity, shapes)
                return Response(content="Box created", status_code=201)
            else:
                return Response(
                    content="Invalid data: expected object with capacity and shapes",
                    status_code=400,
                )
        except Exception:
            return Response(content="Invalid JSON", status_code=400)

    async def rest_test_put(self, request: Request):
        # Add a new element to the array (expects a JSON value)
        body = await request.body()
        try:
            data = json.loads(body)
            added = self._box_for_shapes.add_shape(data["shape"])
            if added:
                return Response(content="Element added", status_code=200)
            else:
                return Response(content="Box is full", status_code=400)
        except Exception:
            return Response(content="Invalid JSON", status_code=400)

    async def rest_test_delete(self, request: Request):
        body = await request.body()
        data = json.loads(body)
        shapes_to_remove = json.loads(data["shapes"])
        deleted = self._box_for_shapes.remove_shape(shapes_to_remove)
        if deleted:
            return Response(content="Removed", status_code=200)
        else:
            return Response(content="Shapes to remove not found in the box", status_code=404)


class _BoxForShapes:
    def __init__(self, capacity, shapes: list[str]):
        self.capacity = capacity
        self._shapes = [s.lower() for s in shapes]

    def add_shape(self, shape: str):
        if len(self._shapes) < self.capacity:
            self._shapes.append(shape.lower())
            return True
        return False

    def remove_shape(self, shapes: list[str]):
        removed = False
        for shape in shapes:
            if shape in self._shapes:
                self._shapes.remove(shape)
                removed = True
        return removed

    def get_shapes(self) -> list[str]:
        if len(self._shapes) == 1:
            return [f"blue {self._shapes[0]}"]
        return self._shapes

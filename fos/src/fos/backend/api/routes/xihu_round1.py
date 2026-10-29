from __future__ import annotations

from pathlib import Path

from litestar import Router, get
from litestar.exceptions import NotFoundException
from litestar.response import File

from fos.xihu_round1 import get_xihu_package_dir, list_xihu_packages, load_xihu_package


@get("/packages")
async def list_packages() -> list[dict]:
    return list_xihu_packages()


@get("/packages/{package_id:str}")
async def read_package(package_id: str) -> dict:
    return load_xihu_package(package_id)


@get("/packages/{package_id:str}/materials/{material_id:str}")
async def download_material(package_id: str, material_id: str) -> File:
    package = load_xihu_package(package_id)
    material = next((item for item in package["materials"] if item["id"] == material_id), None)
    if material is None:
        raise NotFoundException(f"Material '{material_id}' not found in package '{package_id}'")

    file_path = Path(get_xihu_package_dir(package_id) / material["storageRef"]).resolve()
    if not file_path.exists():
        raise NotFoundException(f"Stored material not found: {file_path}")

    return File(
        str(file_path),
        filename=material["filename"],
        content_disposition_type="attachment",
    )


router = Router(
    path="/xihu-round1",
    route_handlers=[list_packages, read_package, download_material],
)

import json
import logging
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlparse

from aidial_sdk.pydantic_v1 import SecretStr

import aiohttp
import httpx

from tests.test_runner.config import TestDialCoreConfig

HTTP_TIMEOUT = 60
logger = logging.getLogger(__name__)

cache_bucket: Dict[str, str] = {}


async def get_bucket(dial_url, headers):
    key = headers.get("Api-Key", None)
    if key in cache_bucket:
        return cache_bucket[key]
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{dial_url}/v1/bucket", headers=headers, timeout=HTTP_TIMEOUT
        ) as response:
            if response.status == 200:
                response_json = await response.json()
                bucket = response_json.get("bucket", None)
                app_data_bucket = response_json.get("appdata", None)
                result = app_data_bucket if app_data_bucket else bucket
                if key:
                    cache_bucket[key] = result
                return result
            else:
                error_message = f'Failed to get bucket for a file. Status: {response.status}, Response: {await response.text()}'
                logger.debug(error_message)
                raise Exception(error_message)


async def get_bucket_items(dial_url, bucket, headers):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{dial_url}/v1/metadata/files/{bucket}/", headers=headers, timeout=HTTP_TIMEOUT
        ) as response:
            if response.status == 200:
                response_json = await response.json()
                return response_json['items']
            else:
                error_message = f'Failed to get bucket for a file. Status: {response.status}, Response: {response.text()}'
                logger.debug(error_message)
                raise Exception(error_message)


async def upload_file(url: str, file_name: str, file_mime: str, headers: dict, file_bytes: bytes):
    async with aiohttp.ClientSession() as session:
        with aiohttp.MultipartWriter('form-data') as mpwriter:
            mpwriter.append(
                file_bytes,
                {
                    'Content-Type': file_mime,
                    'Content-Disposition': f'form-data; name="file"; filename="{file_name}"',
                },
            )
        async with session.put(url, headers=headers, data=mpwriter) as upload_response:
            if upload_response.status == 200:
                metadata = await upload_response.json()
                logger.debug(f'Successfully uploaded file. Response: {metadata}')
                return metadata
            else:
                error_message = f'Failed to upload file. Status: {upload_response.status}, Response: {await upload_response.text()}'
                logger.debug(error_message)
                raise Exception(error_message)


async def upload_attachment(
    dial_url: str, headers: dict, file_name: str, file_bytes: bytes
) -> dict:
    # get bucket:
    bucket = await get_bucket(dial_url, headers)
    file_mime = mimetypes.guess_type(file_name)[0]
    url = f"{dial_url}/v1/files/{bucket}/{file_name}"
    metadata = await upload_file(url, file_name, file_mime, headers, file_bytes)
    logger.info(metadata)
    return metadata


async def search_file_on_core(dial_url, headers, name):
    bucket = await get_bucket(dial_url, headers)
    sub_folders = [bucket]
    for folder in sub_folders:
        items = await get_bucket_items(dial_url, folder, headers)
        for item in items:
            if item.get("nodeType") == 'FOLDER':
                sub_folders.append(f"{folder}/{item['name']}")
            if item['name'] == name:
                return item['url']
    return None


async def upload_file_to_core(dial_url, headers, file_path: Path):
    with open(file_path.absolute(), 'rb') as file:
        file_bytes = file.read()
        return await upload_attachment(dial_url, headers, file_path.name, file_bytes)


def extract_host_port(url):
    parsed_url = urlparse(url)
    host = parsed_url.hostname
    port = parsed_url.port

    # If port is not specified, default to 80 for HTTP
    if port is None:
        port = 80 if parsed_url.scheme == 'http' else 443

    return f"{host}:{port}"

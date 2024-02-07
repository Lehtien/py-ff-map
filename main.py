from fastapi import FastAPI, UploadFile, status, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from typing import Union

from pillow_heif import register_heif_opener
from PIL import Image, ImageChops
import imagehash
import json
import base64
import re

from concurrent.futures import ProcessPoolExecutor

app = FastAPI()
origins = ["https://ff14treasurhunt.netlify.app", "https://ff14treasurhunt.com", "https://www.ff14treasurhunt.com", "http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def handler(request: Request, exc: RequestValidationError):
    print(exc)
    return JSONResponse(content={"error_message": "予期せぬエラーが発生しました。"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


def compare_image_hash(input_image_hash, image_hash):
    return input_image_hash - imagehash.hex_to_hash(image_hash)


@app.post("/ff14_map_treasure_uploadfile/{selected_map}")
async def upload_file(upload_file: UploadFile, selected_map: str, selected_area: Union[str, None] = None):
    upload_file.file.seek(0, 2)
    if upload_file.file.tell() > 10485760:
        return JSONResponse(content={"error_message": "ファイルサイズは10Mbまでアップロードできます。"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    # if ("image/" not in upload_file.content_type) or (upload_file.content_type != "application/octet-stream"):
    #     if "image/" not in mimetypes.guess_type(upload_file.filename)[0]:
    #         return JSONResponse(content={"error_message": "画像のみアップロードできます。"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    register_heif_opener()
    
    image = Image.open(upload_file.file)
    bg = Image.new("RGB", image.size, image.getpixel((0, 0)))
    if image.mode == bg.mode:
        diff = ImageChops.difference(image, bg)
        croprange = diff.convert("RGB").getbbox()
        crop_img = image.crop(croprange)
    else:
        crop_img = image
    
    input_image_hash = imagehash.phash(crop_img)

    filtered_image_hash_list = []
    with open(f"map_hash/image_hash_{selected_map}.json", "r", encoding="utf-8") as f:
        image_hash_list = json.load(f)
        
        if selected_area != None:
            for image_hash in image_hash_list:
                if selected_area in image_hash["name"]:
                    filtered_image_hash_list.append(image_hash)
        else:
            filtered_image_hash_list = image_hash_list                   
        
    diff_dict = {}
    with ProcessPoolExecutor(max_workers=4) as executor:
        for image_hash in filtered_image_hash_list:
            future = executor.submit(compare_image_hash, input_image_hash, image_hash["hash"])
            diff_dict[image_hash["name"]] = future.result()
        executor.shutdown()

        # 座標JSON取得
        coordinates = []
        with open(f"map_place/map_place_{selected_map}.json", "rb") as f:
            place = json.load(f)

        # 昇順並び替え及び小さい値2個取得
        sorted_diff_dict = sorted(diff_dict.items(), key=lambda x: x[1])
        sorted_diff_dict = sorted_diff_dict[0:2]
        sorted_diff_dict = dict((x, y) for x, y in sorted_diff_dict)

        image_base64 = []
        for name in sorted_diff_dict.keys():
            if name is None:
                continue

            with open(f"map_image/{selected_map}/{name}", "rb") as image_file:
                data = base64.b64encode(image_file.read()).decode("utf-8")
                image_base64.append(data)

            #  全体図
            whole_image_name = re.sub("\d", "", name)
            with open(f"map_image/{selected_map}/{whole_image_name}", "rb") as image_file:
                data = base64.b64encode(image_file.read()).decode("utf-8")
                image_base64.append(data)

            # 座標取得
            coordinates.append(list(filter(lambda x: x["name"] == name, place)))
    return JSONResponse(content={"coordinates": coordinates, "image_data": image_base64})

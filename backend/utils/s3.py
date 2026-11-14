# utils/s3.py
# The Vault Campus Marketplace
# Created by Day Ekoi - Iteration 5 4/10/26
# Handles all S3 image upload functionality

import boto3
import os
import uuid
from dotenv import load_dotenv
from flask import current_app


load_dotenv()

BUCKET_NAME = os.getenv("AWS_S3_BUCKET") or os.getenv("S3_BUCKET_NAME")
REGION = os.getenv("AWS_REGION", "us-east-2")

# S3 client setup
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION", "us-east-2")
)

def upload_image_to_s3(file, folder="uploads"):
    """
    Uploads an image file to S3 or save it locally if S3 is not configured.
      and returns the public URL.
    """
    try:
         # Check that a file was selected (Rochele)
        if not file or not file.filename:
            return None
        
        # generate unique filename
        ext = file.filename.rsplit(".", 1)[-1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"

        # upload to S3 - bucket policy handles public read access (edited by rochele)
        if BUCKET_NAME:
            file.seek(0)
            s3_path = f"{folder}/{filename}"

            s3_client.upload_fileobj(
                file,
                BUCKET_NAME,
                s3_path,
                ExtraArgs={"ContentType": file.content_type}
            )

            # return public URL
            url = f"https://{BUCKET_NAME}.s3.{REGION}.amazonaws.com/{s3_path}"
            return url

        #otherwise, save the image locally (rochele)
        upload_folder = os.path.join(
            current_app.static_folder, "uploads", folder
        )

        os.makedirs(upload_folder, exist_ok=True)

        file.seek(0)
        file.save(os.path.join(upload_folder, filename))

        return f"/static/uploads/{folder}/{filename}"

    except Exception as e:
        print(f"Image upload error: {e}")
        return None
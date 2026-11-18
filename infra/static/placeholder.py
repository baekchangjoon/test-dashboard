"""버킷 루트에 index.html이 없을 때만 "준비 중" 자리 표시자를 올린다(Task 10이 게시로 교체한다)."""
import sys

import boto3
from botocore.exceptions import ClientError

BODY = "<!doctype html><meta charset=\"utf-8\"><title>test-dashboard</title><p>준비 중</p>\n"


def main(bucket: str) -> int:
    s3 = boto3.client("s3", region_name="ap-northeast-2")
    try:
        s3.head_object(Bucket=bucket, Key="index.html")
        print("index.html이 이미 있어 건너뛴다")
        return 0
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
            raise
    s3.put_object(Bucket=bucket, Key="index.html", Body=BODY.encode(),
                  ContentType="text/html; charset=utf-8", CacheControl="no-cache")
    print("자리 표시자 index.html을 올렸다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

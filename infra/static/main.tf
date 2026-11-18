terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
  }
}

# 인증은 ~/.aws/credentials default 프로필을 쓴다.
provider "aws" {
  region = "ap-northeast-2"
}

# ACM(CloudFront용)과 CloudFront Function은 us-east-1이어야 한다.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

locals {
  bucket_name = "td-reports-${var.account_id}"
  fqdn        = "reports.${var.domain}"
}

# 기존 zone을 이름으로 찾는다(새 zone을 만들지 않는다).
data "aws_route53_zone" "main" {
  name         = var.domain
  private_zone = false

  lifecycle {
    postcondition {
      condition     = data.aws_caller_identity.current.account_id == var.account_id
      error_message = "현재 자격 증명의 계정이 TD_AWS_ACCOUNT_ID와 다르다."
    }
  }
}

# --- S3: 비공개 버킷, CloudFront OAC로만 읽는다 ---------------------------------------------
resource "aws_s3_bucket" "reports" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "reports" {
  name                              = "td-reports-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "reports_oac" {
  statement {
    sid       = "AllowCloudFrontOAC"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.reports.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.reports.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "reports" {
  bucket     = aws_s3_bucket.reports.id
  policy     = data.aws_iam_policy_document.reports_oac.json
  depends_on = [aws_s3_bucket_public_access_block.reports]
}

# --- ACM(us-east-1), DNS 검증 -----------------------------------------------------------------
resource "aws_acm_certificate" "reports" {
  provider          = aws.us_east_1
  domain_name       = local.fqdn
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# 검증 CNAME(_<hash>.reports.<domain>)만 zone에 추가한다.
resource "aws_route53_record" "acm_validation" {
  for_each = {
    for option in aws_acm_certificate.reports.domain_validation_options : option.domain_name => {
      name   = option.resource_record_name
      type   = option.resource_record_type
      record = option.resource_record_value
    }
  }
  zone_id         = data.aws_route53_zone.main.zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 300
  records         = [each.value.record]
  allow_overwrite = false
}

resource "aws_acm_certificate_validation" "reports" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.reports.arn
  validation_record_fqdns = [for record in aws_route53_record.acm_validation : record.fqdn]
}

# --- CloudFront Function: 디렉터리 URI를 index.html로 재작성 -----------------------------------------
resource "aws_cloudfront_function" "index_rewrite" {
  provider = aws.us_east_1
  name     = "td-reports-index-rewrite"
  runtime  = "cloudfront-js-2.0"
  publish  = true
  comment  = "끝이 /이거나 확장자 없는 경로를 <dir>/index.html로 재작성"
  code     = <<-JS
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      if (uri.endsWith('/')) {
        request.uri = uri + 'index.html';
      } else if (uri.split('/').pop().indexOf('.') === -1) {
        request.uri = uri + '/index.html';
      }
      return request;
    }
  JS
}

# --- CloudFront ------------------------------------------------------------------------------------
resource "aws_cloudfront_distribution" "reports" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  comment             = "test-dashboard reports"
  default_root_object = "index.html"
  aliases             = [local.fqdn]
  price_class         = "PriceClass_200"

  origin {
    domain_name              = aws_s3_bucket.reports.bucket_regional_domain_name
    origin_id                = "reports-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.reports.id
  }

  default_cache_behavior {
    target_origin_id       = "reports-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # Managed-CachingOptimized. 오리진의 Cache-Control(no-cache, immutable)을 따른다.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.index_rewrite.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.reports.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

# --- reports 별칭 레코드(A/AAAA) ----------------------------------------------------------------------
resource "aws_route53_record" "reports" {
  for_each = toset(["A", "AAAA"])
  zone_id  = data.aws_route53_zone.main.zone_id
  name     = local.fqdn
  type     = each.key

  alias {
    name                   = aws_cloudfront_distribution.reports.domain_name
    zone_id                = aws_cloudfront_distribution.reports.hosted_zone_id
    evaluate_target_health = false
  }
}

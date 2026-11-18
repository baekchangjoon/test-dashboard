output "bucket" {
  value = aws_s3_bucket.reports.bucket
}

output "distribution_id" {
  value = aws_cloudfront_distribution.reports.id
}

output "domain" {
  value = local.fqdn
}

output "distribution_domain" {
  value = aws_cloudfront_distribution.reports.domain_name
}

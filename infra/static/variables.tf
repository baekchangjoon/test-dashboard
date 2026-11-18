# 식별자는 커밋하지 않는다. apply.sh가 infra/local.env에서 TF_VAR_*로 주입한다.
variable "account_id" {
  type        = string
  description = "AWS 계정 ID(TD_AWS_ACCOUNT_ID). 버킷 이름과 계정 일치 검사에 쓴다."
}

variable "domain" {
  type        = string
  description = "기본 도메인(TD_DOMAIN). reports.<domain>이 CloudFront 주소다."
}

# =============================================================================
# VARIABLES - Sentient Planner Infrastructure
# =============================================================================

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "localstack_endpoint" {
  description = "LocalStack endpoint URL"
  type        = string
  default     = "http://localhost:4566"
}

variable "s3_bucket_name" {
  description = "S3 bucket name for ASCII art storage"
  type        = string
  default     = "sentient-planner-bucket"
}

variable "dynamodb_table_name" {
  description = "DynamoDB table name for plans and metadata"
  type        = string
  default     = "sentient-planner-table"
}

variable "kinesis_stream_name" {
  description = "Kinesis stream name for input buffer"
  type        = string
  default     = "sentient-planner-stream"
}

variable "sqs_queue_name" {
  description = "SQS queue name for ASCII generation"
  type        = string
  default     = "ascii-gen-queue"
}

variable "secrets_name" {
  description = "Secrets Manager secret name"
  type        = string
  default     = "app-secrets"
}

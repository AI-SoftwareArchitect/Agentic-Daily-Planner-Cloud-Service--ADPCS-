# =============================================================================
# OUTPUTS - Sentient Planner Infrastructure
# =============================================================================

output "api_gateway_url" {
  description = "API Gateway invoke URL"
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}"
}

output "api_gateway_id" {
  description = "API Gateway REST API ID"
  value       = aws_api_gateway_rest_api.sentient_api.id
}

output "s3_bucket_name" {
  description = "S3 bucket name for ASCII art"
  value       = aws_s3_bucket.ascii_storage.bucket
}

output "dynamodb_table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.plans_table.name
}

output "kinesis_stream_name" {
  description = "Kinesis stream name"
  value       = aws_kinesis_stream.input_stream.name
}

output "sqs_queue_url" {
  description = "SQS queue URL for ASCII generation"
  value       = aws_sqs_queue.ascii_gen_queue.url
}

output "auth_lambda_arn" {
  description = "Auth Lambda ARN"
  value       = aws_lambda_function.auth_lambda.arn
}

output "processor_lambda_arn" {
  description = "Processor Lambda ARN"
  value       = aws_lambda_function.processor_lambda.arn
}

output "secrets_arn" {
  description = "Secrets Manager secret ARN"
  value       = aws_secretsmanager_secret.app_secrets.arn
}

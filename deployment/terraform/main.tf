# =============================================================================
# SENTIENT PLANNER - TERRAFORM INFRASTRUCTURE
# LocalStack Compatible AWS Infrastructure
# =============================================================================

terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# PROVIDER CONFIGURATION (LocalStack)
# -----------------------------------------------------------------------------
provider "aws" {
  region                      = var.aws_region
  access_key                  = "test"
  secret_key                  = "test"
  
  # LocalStack specific settings
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    s3             = var.localstack_endpoint
    dynamodb       = var.localstack_endpoint
    kinesis        = var.localstack_endpoint
    sqs            = var.localstack_endpoint
    secretsmanager = var.localstack_endpoint
    lambda         = var.localstack_endpoint
    apigateway     = var.localstack_endpoint
    iam            = var.localstack_endpoint
  }
}

# -----------------------------------------------------------------------------
# S3 BUCKET - ASCII Art Storage
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "ascii_storage" {
  bucket = var.s3_bucket_name
  
  tags = {
    Name        = "Sentient Planner ASCII Storage"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

resource "aws_s3_bucket_versioning" "ascii_versioning" {
  bucket = aws_s3_bucket.ascii_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

# -----------------------------------------------------------------------------
# DYNAMODB TABLE - Plans & Emotion Metadata
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "plans_table" {
  name           = var.dynamodb_table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "UserId"
  range_key      = "Timestamp"

  attribute {
    name = "UserId"
    type = "S"
  }

  attribute {
    name = "Timestamp"
    type = "S"
  }

  # Global Secondary Index for querying by emotion
  global_secondary_index {
    name               = "EmotionIndex"
    hash_key           = "UserId"
    range_key          = "Timestamp"
    projection_type    = "ALL"
  }

  tags = {
    Name        = "Sentient Planner Plans Table"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

# -----------------------------------------------------------------------------
# KINESIS STREAM - Input Buffer
# -----------------------------------------------------------------------------
resource "aws_kinesis_stream" "input_stream" {
  name             = var.kinesis_stream_name
  shard_count      = 1
  retention_period = 24

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  tags = {
    Name        = "Sentient Planner Input Stream"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

# -----------------------------------------------------------------------------
# SQS QUEUE - ASCII Generation Workload
# -----------------------------------------------------------------------------
resource "aws_sqs_queue" "ascii_gen_queue" {
  name                       = var.sqs_queue_name
  delay_seconds              = 0
  max_message_size           = 262144
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 10
  visibility_timeout_seconds = 300

  tags = {
    Name        = "ASCII Generation Queue"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

resource "aws_sqs_queue" "ascii_gen_dlq" {
  name = "${var.sqs_queue_name}-dlq"

  tags = {
    Name        = "ASCII Generation Dead Letter Queue"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

# -----------------------------------------------------------------------------
# SECRETS MANAGER - API Keys & JWT Secret
# -----------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = var.secrets_name
  recovery_window_in_days = 0  # Immediate deletion for local dev

  tags = {
    Name        = "Sentient Planner Secrets"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

# Note: Secret value should be seeded via CLI after terraform apply
# awslocal secretsmanager put-secret-value --secret-id app-secrets --secret-string '{"GEMINI_KEY":"your-key","JWT_SECRET":"your-secret"}'

# -----------------------------------------------------------------------------
# IAM ROLE - Lambda Execution Role
# -----------------------------------------------------------------------------
resource "aws_iam_role" "lambda_execution_role" {
  name = "sentient_planner_lambda_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "Sentient Planner Lambda Role"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "sentient_planner_lambda_policy"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.plans_table.arn
      },
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:ListShards"
        ]
        Resource = aws_kinesis_stream.input_stream.arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage"
        ]
        Resource = aws_sqs_queue.ascii_gen_queue.arn
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.app_secrets.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.ascii_storage.arn}/*"
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# LAMBDA FUNCTIONS
# -----------------------------------------------------------------------------

# Create deployment package directories
resource "null_resource" "create_lambda_packages" {
  provisioner "local-exec" {
    command     = "if not exist ..\\..\\src\\lambdas\\packages mkdir ..\\..\\src\\lambdas\\packages"
    interpreter = ["cmd", "/C"]
  }
}

# Auth Lambda - JWT Validation
data "archive_file" "auth_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../src/lambdas/auth"
  output_path = "${path.module}/../../src/lambdas/packages/auth.zip"

  depends_on = [null_resource.create_lambda_packages]
}

resource "aws_lambda_function" "auth_lambda" {
  filename         = data.archive_file.auth_lambda_zip.output_path
  function_name    = "sentient_planner_auth"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "auth.handler"
  runtime          = "python3.10"
  timeout          = 30
  memory_size      = 128
  source_code_hash = data.archive_file.auth_lambda_zip.output_base64sha256

  environment {
    variables = {
      IS_LOCAL           = "true"
      LOCALSTACK_ENDPOINT = var.localstack_endpoint
      SECRETS_NAME       = var.secrets_name
    }
  }

  tags = {
    Name        = "Sentient Planner Auth Lambda"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

# Processor Lambda - Orchestrator (Gemini + DynamoDB + SQS)
data "archive_file" "processor_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../src/lambdas/processor"
  output_path = "${path.module}/../../src/lambdas/packages/processor.zip"

  depends_on = [null_resource.create_lambda_packages]
}

resource "aws_lambda_function" "processor_lambda" {
  filename         = data.archive_file.processor_lambda_zip.output_path
  function_name    = "sentient_planner_processor"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "processor.handler"
  runtime          = "python3.10"
  timeout          = 120
  memory_size      = 256
  source_code_hash = data.archive_file.processor_lambda_zip.output_base64sha256

  environment {
    variables = {
      IS_LOCAL            = "true"
      LOCALSTACK_ENDPOINT = var.localstack_endpoint
      SECRETS_NAME        = var.secrets_name
      DYNAMODB_TABLE_NAME = var.dynamodb_table_name
      SQS_QUEUE_URL       = aws_sqs_queue.ascii_gen_queue.url
    }
  }

  tags = {
    Name        = "Sentient Planner Processor Lambda"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

# Kinesis Event Source Mapping for Processor Lambda
resource "aws_lambda_event_source_mapping" "kinesis_processor" {
  event_source_arn  = aws_kinesis_stream.input_stream.arn
  function_name     = aws_lambda_function.processor_lambda.arn
  starting_position = "LATEST"
  batch_size        = 10

  depends_on = [aws_iam_role_policy.lambda_policy]
}

# -----------------------------------------------------------------------------
# API GATEWAY
# -----------------------------------------------------------------------------
resource "aws_api_gateway_rest_api" "sentient_api" {
  name        = "Sentient Planner API"
  description = "API for Sentient Planner - Transform thoughts into weekly plans"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = {
    Name        = "Sentient Planner API"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

# /analyze resource
resource "aws_api_gateway_resource" "analyze" {
  rest_api_id = aws_api_gateway_rest_api.sentient_api.id
  parent_id   = aws_api_gateway_rest_api.sentient_api.root_resource_id
  path_part   = "analyze"
}

# POST /analyze
resource "aws_api_gateway_method" "analyze_post" {
  rest_api_id   = aws_api_gateway_rest_api.sentient_api.id
  resource_id   = aws_api_gateway_resource.analyze.id
  http_method   = "POST"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.jwt_authorizer.id
}

# Custom Authorizer
resource "aws_api_gateway_authorizer" "jwt_authorizer" {
  name                   = "JWTAuthorizer"
  rest_api_id            = aws_api_gateway_rest_api.sentient_api.id
  authorizer_uri         = aws_lambda_function.auth_lambda.invoke_arn
  authorizer_credentials = aws_iam_role.lambda_execution_role.arn
  type                   = "TOKEN"
  identity_source        = "method.request.header.Authorization"
}

# Lambda integration for POST /analyze
resource "aws_api_gateway_integration" "analyze_integration" {
  rest_api_id             = aws_api_gateway_rest_api.sentient_api.id
  resource_id             = aws_api_gateway_resource.analyze.id
  http_method             = aws_api_gateway_method.analyze_post.http_method
  integration_http_method = "POST"
  type                    = "AWS"
  uri                     = "arn:aws:apigateway:${var.aws_region}:kinesis:action/PutRecord"
  credentials             = aws_iam_role.lambda_execution_role.arn
  
  request_templates = {
    "application/json" = <<EOF
{
  "StreamName": "${var.kinesis_stream_name}",
  "Data": "$util.base64Encode($input.body)",
  "PartitionKey": "$context.requestId"
}
EOF
  }
}

resource "aws_api_gateway_method_response" "analyze_200" {
  rest_api_id = aws_api_gateway_rest_api.sentient_api.id
  resource_id = aws_api_gateway_resource.analyze.id
  http_method = aws_api_gateway_method.analyze_post.http_method
  status_code = "200"

  response_models = {
    "application/json" = "Empty"
  }
}

resource "aws_api_gateway_integration_response" "analyze_response" {
  rest_api_id = aws_api_gateway_rest_api.sentient_api.id
  resource_id = aws_api_gateway_resource.analyze.id
  http_method = aws_api_gateway_method.analyze_post.http_method
  status_code = aws_api_gateway_method_response.analyze_200.status_code

  response_templates = {
    "application/json" = <<EOF
{
  "message": "Request accepted for processing",
  "requestId": "$context.requestId"
}
EOF
  }

  depends_on = [aws_api_gateway_integration.analyze_integration]
}

# /plan resource
resource "aws_api_gateway_resource" "plan" {
  rest_api_id = aws_api_gateway_rest_api.sentient_api.id
  parent_id   = aws_api_gateway_rest_api.sentient_api.root_resource_id
  path_part   = "plan"
}

# /plan/{userId} resource
resource "aws_api_gateway_resource" "plan_user" {
  rest_api_id = aws_api_gateway_rest_api.sentient_api.id
  parent_id   = aws_api_gateway_resource.plan.id
  path_part   = "{userId}"
}

# GET /plan/{userId}
resource "aws_api_gateway_method" "plan_get" {
  rest_api_id   = aws_api_gateway_rest_api.sentient_api.id
  resource_id   = aws_api_gateway_resource.plan_user.id
  http_method   = "GET"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.jwt_authorizer.id

  request_parameters = {
    "method.request.path.userId" = true
  }
}

# Deploy API
resource "aws_api_gateway_deployment" "api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.sentient_api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.analyze.id,
      aws_api_gateway_method.analyze_post.id,
      aws_api_gateway_integration.analyze_integration.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.analyze_integration,
    aws_api_gateway_integration_response.analyze_response
  ]
}

resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.sentient_api.id
  stage_name    = "dev"

  tags = {
    Name        = "Sentient Planner API Stage"
    Environment = "local"
    Project     = "sentient-planner"
  }
}

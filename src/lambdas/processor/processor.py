"""
Sentient Planner - Processor Lambda (Orchestrator)
===================================================
Core Lambda that processes user input via Kinesis Stream.

This Lambda function:
1. Receives events from Kinesis Stream
2. Calls Gemini 2.5 Flash API for semantic analysis
3. Extracts emotion and generates weekly plan
4. Stores results in DynamoDB
5. Pushes ASCII generation job to SQS (with graceful degradation)
"""

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Gemini SDK import
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Configure logging with JSON format
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
IS_LOCAL = os.environ.get("IS_LOCAL", "false").lower() == "true"
LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
SECRETS_NAME = os.environ.get("SECRETS_NAME", "app-secrets")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "sentient-planner-table")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")

# Cache for secrets
_secrets_cache: Optional[dict] = None


def get_boto3_client(service_name: str) -> Any:
    """
    Create boto3 client with LocalStack endpoint if running locally.
    """
    if IS_LOCAL:
        return boto3.client(
            service_name,
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test"
        )
    return boto3.client(service_name)


def get_boto3_resource(service_name: str) -> Any:
    """
    Create boto3 resource with LocalStack endpoint if running locally.
    """
    if IS_LOCAL:
        return boto3.resource(
            service_name,
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test"
        )
    return boto3.resource(service_name)


def get_secrets() -> dict:
    """
    Retrieve secrets from Secrets Manager (cached).
    """
    global _secrets_cache
    
    if _secrets_cache is not None:
        return _secrets_cache
    
    try:
        client = get_boto3_client("secretsmanager")
        response = client.get_secret_value(SecretId=SECRETS_NAME)
        _secrets_cache = json.loads(response["SecretString"])
        logger.info("Secrets retrieved and cached successfully")
        return _secrets_cache
        
    except ClientError as e:
        logger.error(f"Failed to retrieve secrets: {e}")
        raise


def parse_kinesis_record(record: dict) -> dict:
    """
    Parse Kinesis record and extract user input data.
    """
    try:
        # Decode base64 data from Kinesis
        data = base64.b64decode(record["kinesis"]["data"]).decode("utf-8")
        return json.loads(data)
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse Kinesis record: {e}")
        raise ValueError(f"Invalid Kinesis record format: {e}")


def call_gemini_api(user_text: str, api_key: str) -> dict:
    """
    Call Gemini 2.5 Flash API for semantic analysis.
    
    Returns:
        Dict containing emotion, sentiment_score, and weekly_plan
    """
    if not GEMINI_AVAILABLE:
        logger.warning("Gemini SDK not available, returning fallback response")
        return get_fallback_response()
    
    try:
        # Configure Gemini
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # System prompt for empathetic planner
        system_prompt = """You are an empathetic planner AI. Analyze the user's text and determine their emotional state.
        
Your task:
1. Identify the core emotion from the text
2. Assign a sentiment score (0-100, where 0 is most negative and 100 is most positive)
3. Generate a pragmatic weekly plan tailored to their emotional needs

Output ONLY valid JSON in this exact format:
{
    "emotion": "string - the primary emotion detected (e.g., 'anxious', 'hopeful', 'stressed', 'excited', 'sad', 'neutral')",
    "sentiment_score": number between 0 and 100,
    "weekly_plan": [
        {
            "day": "Monday",
            "tasks": ["task1", "task2", "task3"],
            "focus": "brief focus area for the day",
            "self_care": "one self-care activity"
        }
    ]
}

Make the weekly plan supportive and realistic based on their emotional state."""

        # Generate response
        response = model.generate_content(
            f"{system_prompt}\n\nUser's thoughts:\n{user_text}",
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 2048,
                "response_mime_type": "application/json"
            }
        )
        
        # Parse JSON response
        result = json.loads(response.text)
        
        # Validate required fields
        required_fields = ["emotion", "sentiment_score", "weekly_plan"]
        for field in required_fields:
            if field not in result:
                raise ValueError(f"Missing required field: {field}")
        
        logger.info(f"Gemini analysis complete. Emotion: {result['emotion']}, Score: {result['sentiment_score']}")
        return result
        
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return get_fallback_response()


def get_fallback_response() -> dict:
    """
    Return fallback response when Gemini API fails.
    Ensures user always gets a plan even if AI fails.
    """
    logger.warning("Using fallback response")
    
    return {
        "emotion": "neutral",
        "sentiment_score": 50,
        "weekly_plan": [
            {
                "day": "Monday",
                "tasks": ["Review weekly goals", "Organize workspace", "Plan the week ahead"],
                "focus": "Organization and clarity",
                "self_care": "Take a 15-minute walk"
            },
            {
                "day": "Tuesday",
                "tasks": ["Focus on priority tasks", "Respond to pending messages", "Document progress"],
                "focus": "Productivity",
                "self_care": "Practice deep breathing exercises"
            },
            {
                "day": "Wednesday",
                "tasks": ["Midweek review", "Adjust plans if needed", "Connect with a colleague"],
                "focus": "Adaptation and connection",
                "self_care": "Enjoy a healthy lunch mindfully"
            },
            {
                "day": "Thursday",
                "tasks": ["Continue priority work", "Prepare for end of week", "Learn something new"],
                "focus": "Growth and momentum",
                "self_care": "Listen to calming music"
            },
            {
                "day": "Friday",
                "tasks": ["Complete weekly tasks", "Review accomplishments", "Set intentions for next week"],
                "focus": "Completion and reflection",
                "self_care": "Celebrate small wins"
            },
            {
                "day": "Saturday",
                "tasks": ["Rest and recharge", "Pursue a hobby", "Spend time with loved ones"],
                "focus": "Personal time",
                "self_care": "Sleep in if needed"
            },
            {
                "day": "Sunday",
                "tasks": ["Gentle preparation for the week", "Meal prep", "Relaxation"],
                "focus": "Renewal",
                "self_care": "Practice gratitude journaling"
            }
        ],
        "_fallback": True
    }


def save_to_dynamodb(user_id: str, record_id: str, user_text: str, analysis_result: dict) -> None:
    """
    Save plan and emotion metadata to DynamoDB.
    """
    try:
        dynamodb = get_boto3_resource("dynamodb")
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        item = {
            "UserId": user_id,
            "Timestamp": timestamp,
            "RecordId": record_id,
            "UserText": user_text[:10000],  # Limit text size
            "Emotion": analysis_result.get("emotion", "unknown"),
            "SentimentScore": int(analysis_result.get("sentiment_score", 50)),
            "WeeklyPlan": analysis_result.get("weekly_plan", []),
            "AsciiUrl": None,  # Will be updated by worker
            "AsciiStatus": "pending",
            "CreatedAt": timestamp,
            "IsFallback": analysis_result.get("_fallback", False)
        }
        
        table.put_item(Item=item)
        logger.info(f"Saved record to DynamoDB: UserId={user_id}, RecordId={record_id}")
        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to save to DynamoDB: {e}")
        raise


def push_to_sqs(record_id: str, emotion: str, user_id: str) -> bool:
    """
    Push ASCII generation job to SQS queue.
    Implements graceful degradation - logs error but doesn't fail the Lambda.
    
    Returns:
        True if message was sent successfully, False otherwise
    """
    if not SQS_QUEUE_URL:
        logger.warning("SQS_QUEUE_URL not configured, skipping ASCII generation")
        return False
    
    try:
        sqs = get_boto3_client("sqs")
        
        message = {
            "record_id": record_id,
            "user_id": user_id,
            "emotion": emotion,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message),
            MessageGroupId=user_id if ".fifo" in SQS_QUEUE_URL else None
        )
        
        logger.info(f"SQS message sent for ASCII generation: RecordId={record_id}, Emotion={emotion}")
        return True
        
    except (ClientError, BotoCoreError) as e:
        # Graceful degradation: Log error but don't fail the Lambda
        # User still gets their plan, ASCII art will be marked as pending
        logger.error(f"Failed to push to SQS (graceful degradation): {e}")
        return False


def handler(event: dict, context: Any) -> dict:
    """
    Lambda handler for processing Kinesis stream events.
    """
    logger.info(f"Processing {len(event.get('Records', []))} Kinesis records")
    
    processed_count = 0
    error_count = 0
    
    for record in event.get("Records", []):
        record_id = str(uuid.uuid4())
        
        try:
            # Parse input data
            input_data = parse_kinesis_record(record)
            user_text = input_data.get("text", "")
            user_id = input_data.get("userId", "anonymous")
            
            if not user_text:
                logger.warning(f"Empty text in record, skipping")
                continue
            
            logger.info(f"Processing record for user: {user_id}, text length: {len(user_text)}")
            
            # Get secrets and call Gemini
            secrets = get_secrets()
            gemini_key = secrets.get("GEMINI_KEY", "")
            
            # Analyze with Gemini API
            analysis_result = call_gemini_api(user_text, gemini_key)
            
            # Save to DynamoDB
            save_to_dynamodb(user_id, record_id, user_text, analysis_result)
            
            # Push to SQS for ASCII generation (with graceful degradation)
            push_to_sqs(
                record_id=record_id,
                emotion=analysis_result.get("emotion", "neutral"),
                user_id=user_id
            )
            
            processed_count += 1
            logger.info(f"Successfully processed record: {record_id}")
            
        except Exception as e:
            error_count += 1
            logger.error(f"Failed to process record {record_id}: {e}")
            # Continue processing other records
            continue
    
    response = {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Processing complete",
            "processed": processed_count,
            "errors": error_count
        })
    }
    
    logger.info(f"Batch processing complete: {processed_count} processed, {error_count} errors")
    return response

"""
Sentient Planner - Plan API Handler Lambda
==========================================
Handles GET /plan/{userId} requests to retrieve generated plans.

This Lambda function:
1. Retrieves user plans from DynamoDB
2. Implements circuit breaker pattern - returns plan even if ASCII is pending
3. Returns structured plan response
"""

import json
import logging
import os
from typing import Any, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
IS_LOCAL = os.environ.get("IS_LOCAL", "false").lower() == "true"
LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "sentient-planner-table")


def get_boto3_resource(service_name: str) -> Any:
    """Create boto3 resource with LocalStack endpoint if running locally."""
    if IS_LOCAL:
        return boto3.resource(
            service_name,
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test"
        )
    return boto3.resource(service_name)


def get_user_plans(user_id: str, limit: int = 10) -> List[dict]:
    """
    Retrieve user plans from DynamoDB.
    
    Args:
        user_id: User identifier
        limit: Maximum number of plans to return
    
    Returns:
        List of plan documents
    """
    try:
        dynamodb = get_boto3_resource("dynamodb")
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        
        response = table.query(
            KeyConditionExpression="UserId = :uid",
            ExpressionAttributeValues={
                ":uid": user_id
            },
            ScanIndexForward=False,  # Most recent first
            Limit=limit
        )
        
        return response.get("Items", [])
        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to query DynamoDB: {e}")
        raise


def format_plan_response(plan: dict) -> dict:
    """
    Format plan document for API response.
    Implements circuit breaker - returns plan even if ASCII generation is pending.
    
    Args:
        plan: Raw DynamoDB item
    
    Returns:
        Formatted plan response
    """
    ascii_status = plan.get("AsciiStatus", "pending")
    ascii_url = plan.get("AsciiUrl")
    
    # Circuit breaker: Always return the plan, mark ASCII as pending if not ready
    ascii_info = {
        "status": ascii_status,
        "url": ascii_url,
        "warning": None
    }
    
    if ascii_status == "pending" or not ascii_url:
        ascii_info["warning"] = "Visual generation pending. Your plan is ready below."
    
    return {
        "recordId": plan.get("RecordId"),
        "userId": plan.get("UserId"),
        "createdAt": plan.get("CreatedAt"),
        "emotion": plan.get("Emotion"),
        "sentimentScore": plan.get("SentimentScore"),
        "weeklyPlan": plan.get("WeeklyPlan", []),
        "ascii": ascii_info,
        "isFallback": plan.get("IsFallback", False)
    }


def create_response(status_code: int, body: Any) -> dict:
    """Create API Gateway response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization"
        },
        "body": json.dumps(body, default=str)
    }


def handler(event: dict, context: Any) -> dict:
    """
    Lambda handler for GET /plan/{userId}.
    
    Args:
        event: API Gateway proxy event
        context: Lambda context
    
    Returns:
        API Gateway response
    """
    logger.info(f"Received request: {json.dumps(event, default=str)}")
    
    try:
        # Extract path parameters
        path_params = event.get("pathParameters", {}) or {}
        user_id = path_params.get("userId")
        
        # Also check from authorizer context if available
        if not user_id:
            request_context = event.get("requestContext", {})
            authorizer = request_context.get("authorizer", {})
            user_id = authorizer.get("userId")
        
        if not user_id:
            return create_response(400, {
                "error": "Bad Request",
                "message": "userId is required"
            })
        
        # Get query parameters
        query_params = event.get("queryStringParameters", {}) or {}
        limit = min(int(query_params.get("limit", 10)), 50)  # Max 50
        
        # Retrieve plans
        plans = get_user_plans(user_id, limit)
        
        if not plans:
            return create_response(404, {
                "error": "Not Found",
                "message": f"No plans found for user: {user_id}"
            })
        
        # Format response
        formatted_plans = [format_plan_response(plan) for plan in plans]
        
        response_body = {
            "userId": user_id,
            "planCount": len(formatted_plans),
            "plans": formatted_plans
        }
        
        # Check if any plans have pending ASCII
        pending_count = sum(1 for p in formatted_plans if p["ascii"]["status"] == "pending")
        if pending_count > 0:
            response_body["notice"] = f"{pending_count} plan(s) have visual generation pending"
        
        logger.info(f"Returning {len(formatted_plans)} plans for user: {user_id}")
        return create_response(200, response_body)
        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Database error: {e}")
        return create_response(500, {
            "error": "Internal Server Error",
            "message": "Failed to retrieve plans"
        })
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return create_response(500, {
            "error": "Internal Server Error",
            "message": "An unexpected error occurred"
        })

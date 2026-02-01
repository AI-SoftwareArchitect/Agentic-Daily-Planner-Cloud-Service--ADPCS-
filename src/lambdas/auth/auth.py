"""
Sentient Planner - JWT Authorizer Lambda
=========================================
Custom API Gateway authorizer that validates JWT tokens.

This Lambda function:
1. Extracts Bearer token from Authorization header
2. Validates JWT signature using HS256 algorithm
3. Returns IAM policy (Allow/Deny) for API access
"""

import json
import logging
import os
from typing import Any, Optional

import boto3
import jwt
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
IS_LOCAL = os.environ.get("IS_LOCAL", "false").lower() == "true"
LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
SECRETS_NAME = os.environ.get("SECRETS_NAME", "app-secrets")

# Cache for JWT secret
_jwt_secret_cache: Optional[str] = None


def get_boto3_client(service_name: str) -> Any:
    """
    Create boto3 client with LocalStack endpoint if running locally.
    
    Args:
        service_name: AWS service name (e.g., 'secretsmanager')
    
    Returns:
        Boto3 client configured for local or AWS environment
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


def get_jwt_secret() -> str:
    """
    Retrieve JWT secret from Secrets Manager (cached).
    
    Returns:
        JWT secret string
    
    Raises:
        Exception: If secret cannot be retrieved
    """
    global _jwt_secret_cache
    
    if _jwt_secret_cache is not None:
        logger.info("Using cached JWT secret")
        return _jwt_secret_cache
    
    try:
        client = get_boto3_client("secretsmanager")
        response = client.get_secret_value(SecretId=SECRETS_NAME)
        
        secret_data = json.loads(response["SecretString"])
        _jwt_secret_cache = secret_data.get("JWT_SECRET")
        
        if not _jwt_secret_cache:
            raise ValueError("JWT_SECRET not found in secrets")
        
        logger.info("JWT secret retrieved and cached successfully")
        return _jwt_secret_cache
        
    except ClientError as e:
        logger.error(f"Failed to retrieve secret: {e}")
        raise


def extract_token(auth_header: str) -> str:
    """
    Extract JWT token from Authorization header.
    
    Args:
        auth_header: Authorization header value (e.g., "Bearer eyJ...")
    
    Returns:
        JWT token string
    
    Raises:
        ValueError: If header format is invalid
    """
    if not auth_header:
        raise ValueError("Authorization header is missing")
    
    parts = auth_header.split(" ")
    
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Invalid Authorization header format. Expected: Bearer <token>")
    
    return parts[1]


def validate_token(token: str, secret: str) -> dict:
    """
    Validate JWT token and return decoded payload.
    
    Args:
        token: JWT token string
        secret: JWT secret for signature verification
    
    Returns:
        Decoded token payload
    
    Raises:
        jwt.InvalidTokenError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]}
        )
        logger.info(f"Token validated successfully for user: {payload.get('sub')}")
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        raise
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        raise


def generate_policy(principal_id: str, effect: str, resource: str, context: Optional[dict] = None) -> dict:
    """
    Generate IAM policy document for API Gateway.
    
    Args:
        principal_id: User identifier (from JWT 'sub' claim)
        effect: 'Allow' or 'Deny'
        resource: API Gateway method ARN
        context: Additional context to pass to downstream Lambda
    
    Returns:
        IAM policy document
    """
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource
                }
            ]
        }
    }
    
    if context:
        policy["context"] = context
    
    return policy


def handler(event: dict, context: Any) -> dict:
    """
    Lambda handler for JWT authorization.
    
    Args:
        event: API Gateway authorizer event
        context: Lambda context
    
    Returns:
        IAM policy document
    
    Raises:
        Exception: For unauthorized requests (forces 401 response)
    """
    logger.info(f"Received authorization request: {json.dumps(event, default=str)}")
    
    try:
        # Extract authorization header
        auth_header = event.get("authorizationToken", "")
        method_arn = event.get("methodArn", "*")
        
        # Extract and validate token
        token = extract_token(auth_header)
        jwt_secret = get_jwt_secret()
        payload = validate_token(token, jwt_secret)
        
        # Extract user information
        user_id = payload.get("sub", "unknown")
        
        # Generate Allow policy with user context
        policy = generate_policy(
            principal_id=user_id,
            effect="Allow",
            resource=method_arn,
            context={
                "userId": user_id,
                "email": payload.get("email", ""),
                "tokenExp": str(payload.get("exp", ""))
            }
        )
        
        logger.info(f"Authorization successful for user: {user_id}")
        return policy
        
    except ValueError as e:
        logger.error(f"Authorization failed - Invalid header: {e}")
        raise Exception("Unauthorized")  # Forces 401 response
        
    except jwt.InvalidTokenError as e:
        logger.error(f"Authorization failed - Invalid token: {e}")
        raise Exception("Unauthorized")  # Forces 401 response
        
    except Exception as e:
        logger.error(f"Authorization failed - Unexpected error: {e}")
        raise Exception("Unauthorized")  # Forces 401 response

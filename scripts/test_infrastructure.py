"""
Sentient Planner - End-to-End Test Script
==========================================
Tests the complete flow from API Gateway to DynamoDB.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Optional

import boto3
import jwt
import requests

# Configuration
LOCALSTACK_ENDPOINT = "http://localhost:4566"
API_GATEWAY_ID = "YOUR_API_ID"  # Will be replaced after terraform apply
JWT_SECRET = "YOUR_JWT_SECRET"  # Generated during setup
TEST_USER_ID = "test-user-001"

# API URL (you'll need to get this from Terraform output)
API_BASE_URL = f"{LOCALSTACK_ENDPOINT}/restapis/{API_GATEWAY_ID}/dev/_user_request_"


def get_boto3_client(service_name: str):
    """Create LocalStack boto3 client."""
    return boto3.client(
        service_name,
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test"
    )


def generate_jwt_token(user_id: str, secret: str, exp_hours: int = 24) -> str:
    """Generate a valid JWT token for testing."""
    payload = {
        "sub": user_id,
        "email": f"{user_id}@test.com",
        "exp": datetime.utcnow() + timedelta(hours=exp_hours),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_health_check():
    """Test LocalStack health."""
    print("\n[TEST] LocalStack Health Check")
    print("-" * 40)
    
    try:
        response = requests.get(f"{LOCALSTACK_ENDPOINT}/_localstack/health", timeout=5)
        health = response.json()
        
        print(f"Status: {response.status_code}")
        print(f"Services: {json.dumps(health.get('services', {}), indent=2)}")
        
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_dynamodb():
    """Test DynamoDB table exists."""
    print("\n[TEST] DynamoDB Table")
    print("-" * 40)
    
    try:
        dynamodb = get_boto3_client("dynamodb")
        response = dynamodb.describe_table(TableName="sentient-planner-table")
        
        table = response["Table"]
        print(f"Table Name: {table['TableName']}")
        print(f"Status: {table['TableStatus']}")
        print(f"Item Count: {table.get('ItemCount', 'N/A')}")
        
        return table['TableStatus'] == 'ACTIVE'
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_sqs():
    """Test SQS queue exists."""
    print("\n[TEST] SQS Queue")
    print("-" * 40)
    
    try:
        sqs = get_boto3_client("sqs")
        response = sqs.get_queue_url(QueueName="ascii-gen-queue")
        
        queue_url = response["QueueUrl"]
        print(f"Queue URL: {queue_url}")
        
        # Get queue attributes
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["All"]
        )
        print(f"Messages Available: {attrs['Attributes'].get('ApproximateNumberOfMessages', 0)}")
        
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_s3():
    """Test S3 bucket exists."""
    print("\n[TEST] S3 Bucket")
    print("-" * 40)
    
    try:
        s3 = get_boto3_client("s3")
        response = s3.head_bucket(Bucket="sentient-planner-bucket")
        
        print(f"Bucket: sentient-planner-bucket")
        print(f"Status: Exists")
        
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_secrets():
    """Test Secrets Manager."""
    print("\n[TEST] Secrets Manager")
    print("-" * 40)
    
    try:
        secrets = get_boto3_client("secretsmanager")
        response = secrets.get_secret_value(SecretId="app-secrets")
        
        secret_data = json.loads(response["SecretString"])
        print(f"Secret Name: app-secrets")
        print(f"Keys Available: {list(secret_data.keys())}")
        
        return "GEMINI_KEY" in secret_data and "JWT_SECRET" in secret_data
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_kinesis():
    """Test Kinesis stream."""
    print("\n[TEST] Kinesis Stream")
    print("-" * 40)
    
    try:
        kinesis = get_boto3_client("kinesis")
        response = kinesis.describe_stream(StreamName="sentient-planner-stream")
        
        stream = response["StreamDescription"]
        print(f"Stream Name: {stream['StreamName']}")
        print(f"Status: {stream['StreamStatus']}")
        print(f"Shard Count: {len(stream['Shards'])}")
        
        return stream['StreamStatus'] == 'ACTIVE'
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_direct_kinesis_write():
    """Test direct write to Kinesis (bypass API Gateway)."""
    print("\n[TEST] Direct Kinesis Write")
    print("-" * 40)
    
    try:
        kinesis = get_boto3_client("kinesis")
        
        # Create test payload
        payload = {
            "text": "I'm feeling overwhelmed with work but also excited about my new project. I need to balance my time better.",
            "userId": TEST_USER_ID
        }
        
        import base64
        data = base64.b64encode(json.dumps(payload).encode()).decode()
        
        response = kinesis.put_record(
            StreamName="sentient-planner-stream",
            Data=json.dumps(payload),
            PartitionKey=TEST_USER_ID
        )
        
        print(f"Sequence Number: {response['SequenceNumber']}")
        print(f"Shard ID: {response['ShardId']}")
        
        return response.get('SequenceNumber') is not None
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_api_gateway():
    """Test API Gateway endpoint."""
    print("\n[TEST] API Gateway")
    print("-" * 40)
    
    try:
        apigw = get_boto3_client("apigateway")
        response = apigw.get_rest_apis()
        
        apis = response.get("items", [])
        if apis:
            for api in apis:
                print(f"API Name: {api['name']}")
                print(f"API ID: {api['id']}")
            return True
        else:
            print("No APIs found")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_lambdas():
    """Test Lambda functions."""
    print("\n[TEST] Lambda Functions")
    print("-" * 40)
    
    try:
        lambda_client = get_boto3_client("lambda")
        response = lambda_client.list_functions()
        
        functions = response.get("Functions", [])
        for func in functions:
            print(f"  - {func['FunctionName']} ({func['Runtime']})")
        
        return len(functions) > 0
    except Exception as e:
        print(f"Error: {e}")
        return False


def run_all_tests():
    """Run all infrastructure tests."""
    print("=" * 60)
    print("SENTIENT PLANNER - INFRASTRUCTURE TESTS")
    print("=" * 60)
    
    results = {
        "LocalStack Health": test_health_check(),
        "DynamoDB": test_dynamodb(),
        "S3": test_s3(),
        "SQS": test_sqs(),
        "Secrets Manager": test_secrets(),
        "Kinesis": test_kinesis(),
        "API Gateway": test_api_gateway(),
        "Lambda Functions": test_lambdas(),
    }
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        color = "\033[92m" if result else "\033[91m"
        reset = "\033[0m"
        print(f"{color}{status}{reset} - {test_name}")
        
        if result:
            passed += 1
        else:
            failed += 1
    
    print(f"\nTotal: {passed}/{len(results)} tests passed")
    
    return failed == 0


def main():
    """Main test execution."""
    success = run_all_tests()
    
    if success:
        print("\n[OPTIONAL] Running integration test...")
        print("-" * 40)
        test_direct_kinesis_write()
    
    print("\n" + "=" * 60)
    if success:
        print("All tests passed! Infrastructure is ready.")
    else:
        print("Some tests failed. Please check the configuration.")
    print("=" * 60)


if __name__ == "__main__":
    main()

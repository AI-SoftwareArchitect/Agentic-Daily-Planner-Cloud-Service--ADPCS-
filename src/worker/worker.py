"""
Sentient Planner - ASCII Art Worker (EC2 Simulation)
=====================================================
Long-running worker that processes ASCII generation jobs from SQS.

This worker:
1. Polls SQS queue for ASCII generation jobs
2. Uses PyTorch model to generate ASCII art based on emotion
3. Saves output to S3
4. Updates DynamoDB with ASCII URL
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
import torch
from botocore.exceptions import BotoCoreError, ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Environment variables
IS_LOCAL = os.environ.get("IS_LOCAL", "false").lower() == "true"
LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "sentient-planner-bucket")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "sentient-planner-table")

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def get_boto3_client(service_name: str) -> Any:
    """Create boto3 client with LocalStack endpoint if running locally."""
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


# =============================================================================
# ASCII ART GENERATION
# =============================================================================

# Emotion to ASCII art mapping (fallback when model not available)
EMOTION_ASCII_MAP = {
    "happy": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║           ╰(*´︶`*)╯                 ║
    ║                                      ║
    ║     ♪ ♫ HAPPINESS DETECTED ♫ ♪      ║
    ║                                      ║
    ║   ☆ﾟ.*･｡ﾟ✧*:..｡✧*:..｡✧.*･ﾟ☆       ║
    ║                                      ║
    ║   Your energy radiates positivity!   ║
    ║   Keep spreading those good vibes    ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "excited": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║        ＼(◎o◎)／ EXCITEMENT!        ║
    ║                                      ║
    ║    ★━━━━━━━━★━━━━━━━━★              ║
    ║    ┊ ☆ ┊ ☆ ┊ ☆ ┊ ☆ ┊ ☆ ┊           ║
    ║    ★━━━━━━━━★━━━━━━━━★              ║
    ║                                      ║
    ║   Your enthusiasm is contagious!     ║
    ║   Channel this energy wisely!        ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "hopeful": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║              ☀️                       ║
    ║           ／｜＼                      ║
    ║          ／ ｜ ＼                     ║
    ║             🌱                       ║
    ║                                      ║
    ║      ♡ HOPE BLOOMS WITHIN ♡         ║
    ║                                      ║
    ║   The seeds of tomorrow are          ║
    ║   planted in today's hope            ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "anxious": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║           (・_・;)                   ║
    ║          ／|  |＼                    ║
    ║         ～～～～～～                  ║
    ║                                      ║
    ║      ◈ ANXIETY DETECTED ◈           ║
    ║                                      ║
    ║   Take a deep breath...              ║
    ║   ▓▓▓▓▓▓▓▓▓▓▓                        ║
    ║   One step at a time                 ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "stressed": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║         (╯°□°)╯︵ ┻━┻               ║
    ║                                      ║
    ║     ▓▓▓  STRESS LEVEL: HIGH  ▓▓▓    ║
    ║     ████████████████████████████     ║
    ║                                      ║
    ║   Remember:                          ║
    ║   ┏━━━━━━━━━━━━━━━━━━━━━━┓          ║
    ║   ┃ This too shall pass  ┃          ║
    ║   ┗━━━━━━━━━━━━━━━━━━━━━━┛          ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "sad": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║            (｡•́︿•̀｡)                 ║
    ║                                      ║
    ║          ｡ﾟ(ﾟ´ω`ﾟ)ﾟ｡                ║
    ║                                      ║
    ║      ♡ SADNESS ACKNOWLEDGED ♡        ║
    ║                                      ║
    ║   It's okay to feel this way         ║
    ║   Healing takes time                 ║
    ║   You are not alone ❤️               ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "angry": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║          (╬ಠ益ಠ)                     ║
    ║         ／|  |＼                     ║
    ║        🔥    🔥                      ║
    ║                                      ║
    ║      ⚠ ANGER DETECTED ⚠             ║
    ║                                      ║
    ║   Channel this energy:               ║
    ║   ┌─────────────────────────┐        ║
    ║   │ Breathe → Process → Act │        ║
    ║   └─────────────────────────┘        ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "neutral": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║           (・_・)                    ║
    ║                                      ║
    ║      ━━━━━ NEUTRAL ━━━━━            ║
    ║                                      ║
    ║   ┌────────────────────────┐         ║
    ║   │   Balanced & Present   │         ║
    ║   │        ≋≋≋≋≋≋          │         ║
    ║   │     Mindful Moment     │         ║
    ║   └────────────────────────┘         ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "tired": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║          (－_－) zzZ                 ║
    ║                                      ║
    ║      ～～ FATIGUE MODE ～～          ║
    ║                                      ║
    ║   ▓▒░░░░░░░░░░░░░░░░░░░░░▒▓         ║
    ║            Energy: Low               ║
    ║                                      ║
    ║   Rest is productive too!            ║
    ║   Recharge to come back stronger     ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """,
    "grateful": r"""
    ╔══════════════════════════════════════╗
    ║                                      ║
    ║         (◕‿◕)♡                       ║
    ║                                      ║
    ║      ✿ GRATITUDE FLOWING ✿          ║
    ║                                      ║
    ║   ♡━━━━━━━━━━━━━━━━━━━━━━━━━♡        ║
    ║   │  Thank you for this moment  │   ║
    ║   ♡━━━━━━━━━━━━━━━━━━━━━━━━━♡        ║
    ║                                      ║
    ║   Gratitude transforms everything    ║
    ║                                      ║
    ╚══════════════════════════════════════╝
    """
}


class ASCIIGenerator:
    """ASCII Art Generator using emotion mapping or PyTorch model."""
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize ASCII Generator.
        
        Args:
            model_path: Path to PyTorch model checkpoint (optional)
        """
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        if model_path and os.path.exists(model_path):
            try:
                self._load_model(model_path)
                logger.info(f"Model loaded from {model_path} on {self.device}")
            except Exception as e:
                logger.warning(f"Failed to load model: {e}. Using fallback mapping.")
    
    def _load_model(self, model_path: str) -> None:
        """Load PyTorch model for ASCII generation."""
        # TODO: Implement actual model loading when model is trained
        # For now, we use the emotion mapping
        logger.info(f"Model path provided: {model_path}")
        # checkpoint = torch.load(model_path, map_location=self.device)
        # self.model = ASCIIModel()
        # self.model.load_state_dict(checkpoint)
        # self.model.eval()
    
    def generate(self, emotion: str, record_id: str) -> str:
        """
        Generate ASCII art based on emotion.
        
        Args:
            emotion: Detected emotion string
            record_id: Unique record identifier
        
        Returns:
            ASCII art string
        """
        # Normalize emotion
        emotion_lower = emotion.lower().strip()
        
        # Map similar emotions
        emotion_mapping = {
            "joyful": "happy",
            "elated": "excited",
            "enthusiastic": "excited",
            "optimistic": "hopeful",
            "worried": "anxious",
            "nervous": "anxious",
            "overwhelmed": "stressed",
            "depressed": "sad",
            "melancholic": "sad",
            "furious": "angry",
            "irritated": "angry",
            "exhausted": "tired",
            "fatigued": "tired",
            "thankful": "grateful",
            "appreciative": "grateful"
        }
        
        mapped_emotion = emotion_mapping.get(emotion_lower, emotion_lower)
        
        # Get ASCII art from map or use neutral as fallback
        ascii_art = EMOTION_ASCII_MAP.get(mapped_emotion, EMOTION_ASCII_MAP["neutral"])
        
        # Add metadata footer
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        footer = f"""
    ╔══════════════════════════════════════╗
    ║  Sentient Planner - Emotion Canvas   ║
    ║  ID: {record_id[:8]}                          ║
    ║  Generated: {timestamp}   ║
    ╚══════════════════════════════════════╝
        """
        
        return ascii_art + footer


# =============================================================================
# SQS MESSAGE PROCESSING
# =============================================================================

def poll_sqs_messages(sqs_client: Any, max_messages: int = 10, wait_time: int = 10) -> list:
    """Poll SQS queue for messages."""
    try:
        response = sqs_client.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time,
            AttributeNames=["All"],
            MessageAttributeNames=["All"]
        )
        messages = response.get("Messages", [])
        if messages:
            logger.info(f"Received {len(messages)} messages from SQS")
        return messages
        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to poll SQS: {e}")
        return []


def delete_sqs_message(sqs_client: Any, receipt_handle: str) -> None:
    """Delete processed message from SQS."""
    try:
        sqs_client.delete_message(
            QueueUrl=SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle
        )
        logger.info("Message deleted from SQS")
        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to delete SQS message: {e}")


def upload_to_s3(s3_client: Any, ascii_art: str, record_id: str, user_id: str) -> str:
    """
    Upload ASCII art to S3.
    
    Returns:
        S3 URL of uploaded file
    """
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        key = f"ascii-art/{user_id}/{timestamp}/{record_id}.txt"
        
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=ascii_art.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            Metadata={
                "record_id": record_id,
                "user_id": user_id,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        )
        
        # Generate URL
        if IS_LOCAL:
            url = f"{LOCALSTACK_ENDPOINT}/{S3_BUCKET_NAME}/{key}"
        else:
            url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{key}"
        
        logger.info(f"Uploaded ASCII art to S3: {url}")
        return url
        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to upload to S3: {e}")
        raise


def update_dynamodb(dynamodb_resource: Any, user_id: str, timestamp: str, 
                    record_id: str, ascii_url: str) -> None:
    """Update DynamoDB record with ASCII URL."""
    try:
        table = dynamodb_resource.Table(DYNAMODB_TABLE_NAME)
        
        # Query to find the record by RecordId (since we might not have exact timestamp)
        response = table.query(
            KeyConditionExpression="UserId = :uid",
            FilterExpression="RecordId = :rid",
            ExpressionAttributeValues={
                ":uid": user_id,
                ":rid": record_id
            }
        )
        
        items = response.get("Items", [])
        
        if items:
            item = items[0]
            table.update_item(
                Key={
                    "UserId": item["UserId"],
                    "Timestamp": item["Timestamp"]
                },
                UpdateExpression="SET AsciiUrl = :url, AsciiStatus = :status, AsciiGeneratedAt = :ts",
                ExpressionAttributeValues={
                    ":url": ascii_url,
                    ":status": "completed",
                    ":ts": datetime.now(timezone.utc).isoformat()
                }
            )
            logger.info(f"Updated DynamoDB record: {record_id}")
        else:
            logger.warning(f"Record not found in DynamoDB: {record_id}")
        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to update DynamoDB: {e}")
        raise


def process_message(message: dict, generator: ASCIIGenerator, 
                   s3_client: Any, dynamodb_resource: Any) -> bool:
    """
    Process a single SQS message.
    
    Returns:
        True if processing was successful, False otherwise
    """
    try:
        body = json.loads(message["Body"])
        
        record_id = body.get("record_id")
        emotion = body.get("emotion", "neutral")
        user_id = body.get("user_id", "anonymous")
        timestamp = body.get("timestamp")
        
        if not record_id:
            logger.error("Message missing record_id, skipping")
            return False
        
        logger.info(f"Processing: RecordId={record_id}, Emotion={emotion}")
        
        # Generate ASCII art
        ascii_art = generator.generate(emotion, record_id)
        
        # Upload to S3
        ascii_url = upload_to_s3(s3_client, ascii_art, record_id, user_id)
        
        # Update DynamoDB
        update_dynamodb(dynamodb_resource, user_id, timestamp, record_id, ascii_url)
        
        logger.info(f"Successfully processed message: {record_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to process message: {e}")
        return False


# =============================================================================
# MAIN WORKER LOOP
# =============================================================================

def main() -> None:
    """Main worker loop."""
    logger.info("=" * 60)
    logger.info("Sentient Planner - ASCII Worker Starting")
    logger.info("=" * 60)
    logger.info(f"Environment: {'LOCAL' if IS_LOCAL else 'AWS'}")
    logger.info(f"SQS Queue: {SQS_QUEUE_URL}")
    logger.info(f"S3 Bucket: {S3_BUCKET_NAME}")
    logger.info(f"DynamoDB Table: {DYNAMODB_TABLE_NAME}")
    logger.info("=" * 60)
    
    if not SQS_QUEUE_URL:
        logger.error("SQS_QUEUE_URL is not configured. Exiting.")
        sys.exit(1)
    
    # Initialize clients
    sqs_client = get_boto3_client("sqs")
    s3_client = get_boto3_client("s3")
    dynamodb_resource = get_boto3_resource("dynamodb")
    
    # Initialize ASCII generator
    model_path = os.environ.get("MODEL_PATH", "checkpoints/best-checkpoint.ckpt")
    generator = ASCIIGenerator(model_path=model_path)
    
    logger.info("Worker initialized. Starting polling loop...")
    
    processed_count = 0
    error_count = 0
    
    while not shutdown_requested:
        try:
            # Poll for messages
            messages = poll_sqs_messages(sqs_client, max_messages=10, wait_time=10)
            
            for message in messages:
                if shutdown_requested:
                    logger.info("Shutdown requested, stopping processing")
                    break
                
                success = process_message(message, generator, s3_client, dynamodb_resource)
                
                if success:
                    delete_sqs_message(sqs_client, message["ReceiptHandle"])
                    processed_count += 1
                else:
                    error_count += 1
            
            # Brief pause between polling cycles when no messages
            if not messages:
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(5)  # Wait before retrying
    
    logger.info("=" * 60)
    logger.info("Worker shutting down gracefully")
    logger.info(f"Total processed: {processed_count}")
    logger.info(f"Total errors: {error_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

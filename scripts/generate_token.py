"""
Sentient Planner - JWT Token Generator Utility
==============================================
Generates valid JWT tokens for API testing.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

try:
    import jwt
except ImportError:
    print("PyJWT is required. Install with: pip install PyJWT")
    sys.exit(1)


def generate_token(
    user_id: str,
    secret: str,
    email: str = None,
    exp_hours: int = 24,
    additional_claims: dict = None
) -> str:
    """
    Generate a JWT token.
    
    Args:
        user_id: User identifier (becomes 'sub' claim)
        secret: JWT signing secret
        email: User email (optional)
        exp_hours: Token expiration in hours
        additional_claims: Any additional claims to include
    
    Returns:
        Encoded JWT token string
    """
    now = datetime.utcnow()
    
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=exp_hours),
        "iss": "sentient-planner"
    }
    
    if email:
        payload["email"] = email
    
    if additional_claims:
        payload.update(additional_claims)
    
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        secret: JWT signing secret
    
    Returns:
        Decoded payload dictionary
    """
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        print("Token has expired!")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Generate JWT tokens for Sentient Planner API"
    )
    
    parser.add_argument(
        "--user-id", "-u",
        required=True,
        help="User ID for the token"
    )
    
    parser.add_argument(
        "--secret", "-s",
        required=True,
        help="JWT secret key"
    )
    
    parser.add_argument(
        "--email", "-e",
        default=None,
        help="User email (optional)"
    )
    
    parser.add_argument(
        "--exp-hours", "-x",
        type=int,
        default=24,
        help="Token expiration in hours (default: 24)"
    )
    
    parser.add_argument(
        "--decode", "-d",
        action="store_true",
        help="Decode mode: provide token as --user-id to decode"
    )
    
    parser.add_argument(
        "--curl",
        action="store_true",
        help="Output as curl command example"
    )
    
    args = parser.parse_args()
    
    if args.decode:
        # Decode mode
        payload = decode_token(args.user_id, args.secret)
        if payload:
            print("\nDecoded Token Payload:")
            print(json.dumps(payload, indent=2, default=str))
    else:
        # Generate mode
        token = generate_token(
            user_id=args.user_id,
            secret=args.secret,
            email=args.email or f"{args.user_id}@example.com",
            exp_hours=args.exp_hours
        )
        
        print("\n" + "=" * 60)
        print("Generated JWT Token")
        print("=" * 60)
        print(f"\n{token}\n")
        
        if args.curl:
            print("Example curl command:")
            print("-" * 60)
            print(f'''
curl -X POST "http://localhost:4566/restapis/YOUR_API_ID/dev/_user_request_/analyze" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {token}" \\
  -d '{{"text": "I am feeling happy today!", "userId": "{args.user_id}"}}'
''')
        
        # Show token details
        print("\nToken Details:")
        print("-" * 60)
        payload = decode_token(token, args.secret)
        if payload:
            print(f"User ID (sub): {payload.get('sub')}")
            print(f"Email: {payload.get('email')}")
            print(f"Issued At: {datetime.fromtimestamp(payload.get('iat', 0))}")
            print(f"Expires At: {datetime.fromtimestamp(payload.get('exp', 0))}")


if __name__ == "__main__":
    main()

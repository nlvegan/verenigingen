#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deployment Notifications
Send notifications about deployment status
"""

import json
import requests
from datetime import datetime


class DeploymentNotifier:
    """Send deployment notifications to various channels"""
    
    def __init__(self):
        # Load notification config from environment or config file
        self.config = self.load_config()
        
    def load_config(self):
        """Load notification configuration"""
        # In production, these would come from environment variables
        return {
            "slack_webhook": "",  # Set SLACK_WEBHOOK env var
            "email_recipients": ["admin@veganisme.net"],
            "discord_webhook": "",  # Set DISCORD_WEBHOOK env var
        }
        
    def send_slack_notification(self, message, status="info"):
        """Send notification to Slack"""
        if not self.config.get("slack_webhook"):
            print("  ℹ️  Slack webhook not configured")
            return
            
        colors = {
            "started": "#0080ff",
            "success": "#00ff00",
            "failed": "#ff0000",
            "rollback": "#ff8000",
            "info": "#808080"
        }
        
        payload = {
            "attachments": [{
                "color": colors.get(status, colors["info"]),
                "title": "Deployment Notification",
                "text": message,
                "timestamp": int(datetime.utcnow().timestamp())
            }]
        }
        
        try:
            response = requests.post(
                self.config["slack_webhook"],
                json=payload,
                timeout=10
            )
            if response.status_code == 200:
                print("  ✅ Slack notification sent")
        except Exception as e:
            print(f"  ❌ Failed to send Slack notification: {e}")
            
    def send_discord_notification(self, message, status="info"):
        """Send notification to Discord"""
        if not self.config.get("discord_webhook"):
            print("  ℹ️  Discord webhook not configured")
            return
            
        colors = {
            "started": 0x0080ff,
            "success": 0x00ff00,
            "failed": 0xff0000,
            "rollback": 0xff8000,
            "info": 0x808080
        }
        
        payload = {
            "embeds": [{
                "title": "Deployment Notification",
                "description": message,
                "color": colors.get(status, colors["info"]),
                "timestamp": datetime.utcnow().isoformat()
            }]
        }
        
        try:
            response = requests.post(
                self.config["discord_webhook"],
                json=payload,
                timeout=10
            )
            if response.status_code == 204:
                print("  ✅ Discord notification sent")
        except Exception as e:
            print(f"  ❌ Failed to send Discord notification: {e}")
            
    def send_email_notification(self, subject, message):
        """Send email notification"""
        # In production, this would use Frappe's email system
        print(f"  📧 Email notification: {subject}")
        print(f"     Recipients: {', '.join(self.config['email_recipients'])}")
        
    def format_deployment_message(self, environment, version, status, details=None):
        """Format deployment message"""
        emoji_map = {
            "started": "🚀",
            "success": "✅",
            "failed": "❌",
            "rollback": "⚠️"
        }
        
        emoji = emoji_map.get(status, "ℹ️")
        
        message = f"{emoji} Deployment to {environment.upper()}"
        
        if version:
            message += f" (v{version})"
            
        message += f" - {status.upper()}"
        
        if details:
            message += f"\n\nDetails:\n{details}"
            
        return message
        
    def notify(self, environment, version=None, status="info", notify_all=False, details=None):
        """Send deployment notification"""
        print(f"\n📢 Sending deployment notifications...")
        
        message = self.format_deployment_message(environment, version, status, details)
        
        # Send to appropriate channels based on environment and status
        if environment == "production" or notify_all:
            # Production deployments notify all channels
            self.send_slack_notification(message, status)
            self.send_discord_notification(message, status)
            self.send_email_notification(
                f"Deployment {status}: {environment}",
                message
            )
        else:
            # Staging deployments only notify Slack
            self.send_slack_notification(message, status)
            
        # Always notify on failures or rollbacks
        if status in ["failed", "rollback"]:
            self.send_email_notification(
                f"URGENT: Deployment {status} on {environment}",
                message
            )


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Send deployment notifications")
    parser.add_argument("--environment", required=True, choices=["staging", "production"])
    parser.add_argument("--version", help="Deployment version")
    parser.add_argument("--status", required=True, 
                       choices=["started", "success", "failed", "rollback"])
    parser.add_argument("--notify-all", action="store_true", 
                       help="Notify all channels regardless of environment")
    parser.add_argument("--details", help="Additional details")
    
    args = parser.parse_args()
    
    notifier = DeploymentNotifier()
    notifier.notify(
        environment=args.environment,
        version=args.version,
        status=args.status,
        notify_all=args.notify_all,
        details=args.details
    )


if __name__ == "__main__":
    main()
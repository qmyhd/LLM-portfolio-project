// PM2 Ecosystem Configuration for Discord Bot with AWS Secrets Manager
// 
// This configuration keeps the Discord bot running continuously on EC2.
// PM2 automatically restarts the bot if it crashes.
// Secrets are loaded from AWS Secrets Manager at startup.
//
// Installation:
//   npm install -g pm2
//
// Usage:
//   pm2 start ecosystem.config.js
//   pm2 status                    # Check status
//   pm2 logs discord-bot          # View logs
//   pm2 restart discord-bot       # Restart
//   pm2 stop discord-bot          # Stop
//   pm2 save                      # Save process list
//   pm2 startup                   # Configure auto-start on boot
//
// Prerequisites:
//   - IAM role with secretsmanager:GetSecretValue permission
//   - Secret "llm-portfolio/production" in AWS Secrets Manager

module.exports = {
  apps: [
    {
      name: 'discord-bot',
      // Use wrapper script that loads secrets from AWS Secrets Manager
      script: 'scripts/start_bot_with_secrets.py',
      cwd: '/home/ec2-user/LLM-portfolio-project',
      
      // Python interpreter (use virtual environment)
      interpreter: '/home/ec2-user/LLM-portfolio-project/.venv/bin/python',
      interpreter_args: '',
      
      // Environment - configure AWS Secrets Manager
      env: {
        PYTHONPATH: '/home/ec2-user/LLM-portfolio-project',
        PYTHONUNBUFFERED: '1',
        // AWS Secrets Manager configuration
        USE_AWS_SECRETS: '1',
        AWS_REGION: 'us-east-1',
        // Main app secrets (Discord, OpenAI, Supabase, SnapTrade, Databento)
        AWS_SECRET_NAME: 'qqqAppsecrets',
        // RDS secrets (OHLCV database)
        AWS_RDS_SECRET_NAME: 'RDS/ohlcvdata'
      },
      
      // Process management
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      
      // Restart behavior
      max_restarts: 10,
      min_uptime: '30s',
      restart_delay: 5000,
      
      // Logging
      log_file: '/var/log/discord-bot/combined.log',
      out_file: '/var/log/discord-bot/out.log',
      error_file: '/var/log/discord-bot/error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      
      // Graceful shutdown
      kill_timeout: 10000,
      wait_ready: true,
      listen_timeout: 10000,
      
      // Daily restart at 5 AM UTC (optional - for memory cleanup)
      cron_restart: '0 5 * * *'
    }
  ]
};

# Telegram Git Bot

A Telegram bot that automatically saves messages to your Git repository.

## Setup Instructions

### 1. Prerequisites
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Git repository URL
- Replit account

### 2. Environment Variables
Set these in your Replit environment:

- `BOT_TOKEN`: Your Telegram bot token
- `WEBHOOK_URL`: Your Replit app URL (e.g., `https://your-project.your-username.repl.co`)
- `GIT_REPO_URL`: Your Git repository URL
- `GIT_BRANCH`: Git branch (default: main)

### 3. Git Configuration
The bot will automatically clone your repository and push changes.

### 4. Commands
- `/start` - Start the bot
- `/help` - Show help
- `/gitstatus` - Check Git status
- `/save <filename>` - Save text to specific file

## Deployment
1. Fork this to your Replit
2. Set environment variables
3. Run the project
4. Your bot is ready!

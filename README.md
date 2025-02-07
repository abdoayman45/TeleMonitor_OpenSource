# Telegram Notification Tool Setup Guide

This tool allows you to input specific keywords and the IDs of certain Telegram stickers. It monitors all your Telegram messages, and if any message contains one of the specified keywords or a sticker with a matching ID, the tool triggers a bot to send you a Telegram notification with the message link and details.

This functionality is especially useful during competitions, as you can set up your desired keywords or stickers instead of manually monitoring every notification. **Note:** You must enable bot notifications for the tool to work.

Additionally, the tool includes a **"How it Works"** button. Clicking it will redirect you to tutorial videos that explain how to set it up step-by-step.

---

## System Requirements and Setup Guide

### 1️⃣ Enable Bot Notifications  
To receive notifications, follow these steps:  
- Open Telegram and search for the bot: `@notificmemybot`.  
- Click **Start** to activate the bot.  
- Watch this video for a detailed tutorial: [Click Here](https://t.me/tele_monitor_app/5).  

### 2️⃣ Get Your Telegram User ID  
To retrieve your User ID:  
- Open Telegram and search for `@userinfobot`.  
- Send any message to the bot.  
- The bot will reply with your User ID.  

### 3️⃣ Obtain `api_id` and `api_hash`  
Follow these steps to get your API credentials:  

1. **Visit Telegram’s My Applications Page**  
   - Open your browser and go to [my.telegram.org](https://my.telegram.org).  
   - Log in using your Telegram phone number.  

2. **Navigate to the API Development Section**  
   - Click on **"API Development Tools"** after logging in.  

3. **Create a New Application**  
   - Fill in the required fields:  
     - **App title** – Any name you prefer.  
     - **Short name** – A unique identifier.  
     - **Platform** – Choose any option (this does not affect functionality).  
     - **Description** – Optional.  
   - Click **"Create Application"**.  

4. **Retrieve Your API Credentials**  
   - Once the application is created, your `api_id` and `api_hash` will be displayed.  
   - Save these credentials securely.  
   - For a step-by-step guide, watch this video: [Click Here](https://t.me/tele_monitor_app/6).  

### ⚠️ Important Notes  
- 🚨 **Never share your `api_id` and `api_hash` publicly.**  
- 🔑 These credentials provide access to Telegram's API, so handle them with care.

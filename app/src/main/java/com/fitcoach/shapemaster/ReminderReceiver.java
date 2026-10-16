package com.fitcoach.shapemaster;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import java.util.Calendar;

/** User-enabled, inexact daily reminders. No health data in the lock-screen message. */
public class ReminderReceiver extends BroadcastReceiver {
    private static PendingIntent pending(Context context) {
        return PendingIntent.getBroadcast(context, 7301, new Intent(context, ReminderReceiver.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
    public static void schedule(Context context) {
        android.content.SharedPreferences prefs=context.getSharedPreferences("reminders",Context.MODE_PRIVATE);
        AlarmManager alarms=(AlarmManager)context.getSystemService(Context.ALARM_SERVICE);
        if (alarms==null) return;
        alarms.cancel(pending(context));
        if (!prefs.getBoolean("enabled",false)) return;
        Calendar next=Calendar.getInstance();
        next.set(Calendar.HOUR_OF_DAY,prefs.getInt("hour",20));
        next.set(Calendar.MINUTE,prefs.getInt("minute",0));next.set(Calendar.SECOND,0);next.set(Calendar.MILLISECOND,0);
        if(next.getTimeInMillis()<=System.currentTimeMillis())next.add(Calendar.DAY_OF_YEAR,1);
        alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,next.getTimeInMillis(),pending(context));
    }
    @Override public void onReceive(Context context,Intent intent) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction()) || Intent.ACTION_TIMEZONE_CHANGED.equals(intent.getAction())
                || Intent.ACTION_TIME_CHANGED.equals(intent.getAction())) {schedule(context);return;}
        if (!context.getSharedPreferences("reminders",Context.MODE_PRIVATE).getBoolean("enabled",false))return;
        new WebAppInterface(context,null).tryNotify("轻塑 · 今日记录", "方便时回顾今天的饮食、饮水和活动记录。");
        schedule(context);
    }
}

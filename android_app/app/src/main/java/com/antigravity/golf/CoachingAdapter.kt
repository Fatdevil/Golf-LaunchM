package com.antigravity.golf

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONArray
import org.json.JSONObject

class CoachingAdapter : RecyclerView.Adapter<CoachingAdapter.ViewHolder>() {

    private val items = mutableListOf<JSONObject>()

    fun setData(newItems: List<JSONObject>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val timestampText: TextView = view.findViewById(R.id.timestampText)
        val summaryText: TextView = view.findViewById(R.id.summaryText)
        val primaryFindingText: TextView = view.findViewById(R.id.primaryFindingText)
        val pointsText: TextView = view.findViewById(R.id.pointsText)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_coaching_report, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = items[position]
        
        // Format timestamp safely
        var dateStr = item.optString("created_at", "Unknown Date")
        if (dateStr.length >= 10) {
            dateStr = dateStr.substring(0, 10) + " " + dateStr.substring(11, 16)
        }
        holder.timestampText.text = "SESSION: $dateStr"
        
        holder.summaryText.text = item.optString("session_summary", "")
        holder.primaryFindingText.text = item.optString("primary_finding", "")

        val pointsJsonStr = item.optString("coaching_points_json", "[]")
        var pointsBulletStr = ""
        try {
            val pointsArr = JSONArray(pointsJsonStr)
            for (i in 0 until pointsArr.length()) {
                val p = pointsArr.getJSONObject(i)
                val focus = p.optString("focus_area", "")
                val drill = p.optString("drill", "")
                pointsBulletStr += "• $focus: $drill\n"
            }
        } catch (e: Exception) {
            // ignore
        }
        holder.pointsText.text = pointsBulletStr.trim()
    }

    override fun getItemCount() = items.size
}

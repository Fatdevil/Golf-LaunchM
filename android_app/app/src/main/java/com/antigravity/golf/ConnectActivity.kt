package com.antigravity.golf

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.textfield.TextInputEditText
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class ConnectActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_connect)

        val prefs = getSharedPreferences("GolfPrefs", Context.MODE_PRIVATE)
        val ipInput = findViewById<TextInputEditText>(R.id.ipInput)
        val portInput = findViewById<TextInputEditText>(R.id.portInput)
        val coachingInput = findViewById<TextInputEditText>(R.id.coachingPortInput)
        val connectBtn = findViewById<Button>(R.id.connectBtn)

        ipInput.setText(prefs.getString("last_ip", ""))
        portInput.setText(prefs.getString("last_port", "8080"))
        coachingInput.setText(prefs.getString("coaching_port", "8766"))

        connectBtn.setOnClickListener {
            val ip = ipInput.text.toString().trim()
            val port = portInput.text.toString().trim()
            val coachingPort = coachingInput.text.toString().trim()

            if (ip.isEmpty() || port.isEmpty()) {
                Toast.makeText(this, "IP and Port required", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            prefs.edit()
                .putString("last_ip", ip)
                .putString("last_port", port)
                .putString("coaching_port", coachingPort)
                .apply()

            connectBtn.isEnabled = false
            connectBtn.text = "CONNECTING..."

            testConnection(ip, port)
        }
    }

    private fun testConnection(ip: String, port: String) {
        thread {
            try {
                val url = URL("http://$ip:$port/trajectory_viewer.html")
                val conn = url.openConnection() as HttpURLConnection
                conn.connectTimeout = 3000
                conn.readTimeout = 3000
                conn.requestMethod = "GET"
                
                val code = conn.responseCode
                runOnUiThread {
                    if (code == 200) {
                        launchMain(ip, port)
                    } else {
                        showError()
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { showError() }
            }
        }
    }

    private fun showError() {
        val connectBtn = findViewById<Button>(R.id.connectBtn)
        connectBtn.isEnabled = true
        connectBtn.text = "CONNECT"
        Toast.makeText(this, "Cannot reach bridge. Is main.py running?", Toast.LENGTH_LONG).show()
    }

    private fun launchMain(ip: String, port: String) {
        val intent = Intent(this, MainActivity::class.java).apply {
            putExtra("IP", ip)
            putExtra("PORT", port)
        }
        startActivity(intent)
        finish()
    }
}

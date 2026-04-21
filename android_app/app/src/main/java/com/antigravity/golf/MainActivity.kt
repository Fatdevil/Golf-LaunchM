package com.antigravity.golf

import android.app.AlertDialog
import android.content.Context
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.google.android.material.bottomnavigation.BottomNavigationView

class MainActivity : AppCompatActivity() {

    private lateinit var overlayToolbar: View
    private lateinit var connectionText: TextView
    private lateinit var wsStatusDot: View
    private val hideHandler = Handler(Looper.getMainLooper())
    private val hideRunnable = java.lang.Runnable { overlayToolbar.visibility = View.GONE }

    private lateinit var tracerFragment: WebViewFragment
    private lateinit var dashboardFragment: WebViewFragment
    private lateinit var coachingFragment: CoachingFragment
    
    private var activeFragment: Fragment? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Immersive and Keep screen on
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.setDecorFitsSystemWindows(false)
        window.insetsController?.let {
            it.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
            it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }

        setContentView(R.layout.activity_main)

        overlayToolbar = findViewById(R.id.overlayToolbar)
        connectionText = findViewById(R.id.connectionText)
        wsStatusDot = findViewById(R.id.wsStatusDot)

        val ip = intent.getStringExtra("IP") ?: ""
        val port = intent.getStringExtra("PORT") ?: "8080"
        
        val prefs = getSharedPreferences("GolfPrefs", Context.MODE_PRIVATE)
        val coachingPort = prefs.getString("coaching_port", "8766") ?: "8766"

        connectionText.text = "$ip"

        findViewById<View>(R.id.btnDisconnect).setOnClickListener { promptDisconnect() }
        findViewById<View>(R.id.btnReload).setOnClickListener {
            (activeFragment as? WebViewFragment)?.reload()
        }

        tracerFragment = WebViewFragment.newInstance("http://$ip:$port/trajectory_viewer.html")
        dashboardFragment = WebViewFragment.newInstance("http://$ip:$port/dashboard.html")
        coachingFragment = CoachingFragment.newInstance("http://$ip:$coachingPort/coaching/history/player1")

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottomNav)
        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_tracer -> switchFragment(tracerFragment)
                R.id.nav_dashboard -> switchFragment(dashboardFragment)
                R.id.nav_coaching -> switchFragment(coachingFragment)
            }
            true
        }

        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction()
                .add(R.id.fragmentContainer, tracerFragment, "tracer")
                .add(R.id.fragmentContainer, dashboardFragment, "dashboard").hide(dashboardFragment)
                .add(R.id.fragmentContainer, coachingFragment, "coaching").hide(coachingFragment)
                .commit()
            activeFragment = tracerFragment
        }

        scheduleOverlayHide()
    }

    private fun switchFragment(target: Fragment) {
        if (target == activeFragment) return
        supportFragmentManager.beginTransaction()
            .hide(activeFragment!!)
            .show(target)
            .commit()
        activeFragment = target
        scheduleOverlayHide()
    }

    fun updateWsStatus(connected: Boolean) {
        runOnUiThread {
            wsStatusDot.setBackgroundResource(
                if (connected) R.drawable.circle_green else R.drawable.circle_red
            )
        }
    }

    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (overlayToolbar.visibility == View.GONE) {
            overlayToolbar.visibility = View.VISIBLE
        }
        scheduleOverlayHide()
        return super.dispatchTouchEvent(ev)
    }

    private fun scheduleOverlayHide() {
        hideHandler.removeCallbacks(hideRunnable)
        hideHandler.postDelayed(hideRunnable, 3000)
    }

    override fun onBackPressed() {
        if (activeFragment is WebViewFragment && (activeFragment as WebViewFragment).canGoBack()) {
            (activeFragment as WebViewFragment).goBack()
        } else {
            promptDisconnect()
        }
    }

    private fun promptDisconnect() {
        AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle("Disconnect")
            .setMessage("Disconnect from bridge?")
            .setPositiveButton("Yes") { _, _ -> finish() }
            .setNegativeButton("No", null)
            .show()
    }

    fun getIp(): String = intent.getStringExtra("IP") ?: ""
}

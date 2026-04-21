package com.antigravity.golf

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment

class WebViewFragment : Fragment() {

    private lateinit var webView: WebView
    private lateinit var errorView: LinearLayout
    private lateinit var errorText: TextView
    private lateinit var retryBtn: Button

    private var targetUrl: String = ""
    private val handler = Handler(Looper.getMainLooper())
    private var isTrackingWs = false

    companion object {
        fun newInstance(url: String): WebViewFragment {
            val frag = WebViewFragment()
            val args = Bundle()
            args.putString("URL", url)
            frag.arguments = args
            return frag
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        targetUrl = arguments?.getString("URL") ?: ""
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        val root = inflater.inflate(R.layout.fragment_webview, container, false)
        
        webView = root.findViewById(R.id.webView)
        errorView = root.findViewById(R.id.errorView)
        errorText = root.findViewById(R.id.errorText)
        retryBtn = root.findViewById(R.id.retryBtn)

        setupWebView()

        retryBtn.setOnClickListener {
            errorView.visibility = View.GONE
            webView.visibility = View.VISIBLE
            webView.loadUrl(targetUrl)
        }

        if (savedInstanceState == null) {
            webView.loadUrl(targetUrl)
        } else {
            webView.restoreState(savedInstanceState)
        }

        return root
    }

    private fun setupWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            mediaPlaybackRequiresUserGesture = false
            setLayerType(View.LAYER_TYPE_HARDWARE, null)
        }

        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                if (!isTrackingWs) {
                    isTrackingWs = true
                    startWsTracking()
                }
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                if (request?.isForMainFrame == true) {
                    webView.visibility = View.GONE
                    errorView.visibility = View.VISIBLE
                }
            }
        }
    }

    private val wsPoller = object : Runnable {
        override fun run() {
            if (context == null || !isAdded) return
            
            webView.evaluateJavascript("document.getElementById('ws-status') ? document.getElementById('ws-status').style.backgroundColor : 'none'") { result ->
                val res = result?.replace("\"", "") ?: ""
                val isConnected = res.contains("rgb(16, 185, 129)") || res.contains("#10b981")
                (activity as? MainActivity)?.updateWsStatus(isConnected)
            }
            handler.postDelayed(this, 2000)
        }
    }

    private fun startWsTracking() {
        handler.removeCallbacks(wsPoller)
        handler.post(wsPoller)
    }

    override fun onDestroyView() {
        handler.removeCallbacks(wsPoller)
        isTrackingWs = false
        super.onDestroyView()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }

    fun canGoBack(): Boolean = webView.canGoBack()
    
    fun goBack() {
        webView.goBack()
    }

    fun reload() {
        webView.reload()
    }
}

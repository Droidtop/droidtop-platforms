package plugin

import dev.droidtop.pluginhost.DroidtopPlugin
import dev.droidtop.pluginhost.PluginArgs
import dev.droidtop.pluginhost.PluginCall
import dev.droidtop.pluginhost.PluginCapability
import dev.droidtop.pluginhost.PluginContext
import dev.droidtop.pluginhost.PluginErrorCode
import dev.droidtop.pluginhost.PluginReply
import dev.droidtop.pluginhost.PluginResult
import org.json.JSONObject

/**
 * The entry point named by "entryClass" in manifest.template.json. droidtop calls
 * [handle] with one envelope per call (point, op, args) and expects an ok or error
 * reply; docs/plugin-api.md lists the points and what each op must answer.
 */
class Plugin : DroidtopPlugin {
    private var context: PluginContext? = null

    override fun onLoad(context: PluginContext) {
        this.context = context
    }

    override fun invoke(capability: PluginCapability, args: PluginArgs): PluginResult =
        PluginResult.failure("this plugin answers contract 2 calls only")

    override fun handle(call: PluginCall): PluginReply = when {
        call.point == "ui.status_tile" && call.op == "state" ->
            PluginReply.ok(JSONObject().put("label", "Hello").put("value", "It works"))
        else -> PluginReply.error(PluginErrorCode.UNSUPPORTED, "Unsupported: ${call.point} ${call.op}")
    }
}

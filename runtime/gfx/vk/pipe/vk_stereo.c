// Stereo 3D (cfg STEREO=1): the game's picture for a left and a right eye, presented side by side.
//
// Where the eye comes from. The translator (sm86/translate/glsl/head.py, MKW_STEREO_GLSL=1) gives every vertex shader
// three specialization constants and a shear of the clip position, x += eye * SEP * (w - CONV), which is exactly a
// lateral camera offset under a perspective projection. Their 0 defaults fold the shear away, so a module built without
// them set is the mono one the game has always had; vk_spirv_patch.c's spirv_stereo writes one eye's values in, and
// make_module asks this file which eye to write (vk_pipeline.c).
//
// One eye per submission. A frame cannot afford to be recorded twice: recording is the 19 ms CPU bottleneck of the
// replay (the game's own logic is 3.4 ms), so two views per frame would halve the frame rate. Instead consecutive
// submissions alternate eyes and the present pairs the newest image of each eye into one side-by-side picture: each eye
// sees every other frame, 30 a second at the game's 60, for the price of one extra full-screen blit. Drawing both eyes
// per frame is the M2 step and multiview (VK_KHR_multiview, one recording, two views on the GPU) is M3.
//
// The eye is part of the pipeline key (GKey.eye, and the vertex library's PrKey.eye), so the two eyes' pipelines are
// built and cached side by side and a draw picks the one its submission was recorded with: no per-draw branch.

#include <math.h>

#include "cfg.h"
#include "host.h"
#include "vk.h"
#include "vk_stereo.h"

static int on = -1;          // -1 until cfg is read, then 0 or 1
static float sep, conv;      // STEREO_SEP, STEREO_CONV
static int eye = -1;         // the submission being recorded: -1 left, +1 right
static _Thread_local int screen_pass;   // this draw covers the screen itself (see vk_stereo_screen_pass)

// Reads the settings once. Called from the pipeline code (both the drawing and the building threads), so the values
// must be read before any build: vk_stereo_init runs at the device's startup (vk_backend.c).
void vk_stereo_init(void) {
    if (on >= 0) return;
    int o = cfg_bool("MKW_STEREO");
    float s = (float)cfg_double("MKW_STEREO_SEP"), c = (float)cfg_double("MKW_STEREO_CONV");
    if (o && !(s > 0.0f)) o = 0;   // a separation of 0 is the mono picture: do not pay for two of them
    sep = s, conv = c, eye = -1;
    __atomic_store_n(&on, o, __ATOMIC_RELAXED);
    if (o)
        rt_log("vk: stereo 3D on: sep %.4f (half the eye separation, clip units), conv %.2f (the w where the eyes "
               "agree); one eye per submission, left first, presented side by side", sep, conv);
}

int vk_stereo_on(void) {
    if (__atomic_load_n(&on, __ATOMIC_RELAXED) < 0) vk_stereo_init();
    return __atomic_load_n(&on, __ATOMIC_RELAXED);
}

float vk_stereo_sep(void) { vk_stereo_on(); return sep; }
float vk_stereo_conv(void) { vk_stereo_on(); return conv; }

// The eye of the submission being recorded, 0 when mono: what make_module writes into a shader's constants.
int vk_stereo_eye(void) { return vk_stereo_on() ? eye : 0; }

// The next submission shows the other eye. Called by the replay thread after a present is queued, so every submission of
// one frame (a frame may submit more than once) keeps the eye it started with.
void vk_stereo_next(void) {
    if (vk_stereo_on()) eye = -eye;
}

// For the present: is this eye the one the newest image holds, and which half of the picture does it go to.
int vk_stereo_side_left(void) { return eye < 0; }

// A full-screen draw (a few vertices, scissor covering the pass: the post-process, the composition, the final blit)
// draws the screen itself, not the scene. Shearing its clip x slides the whole picture inside its texture - a black
// band on one edge and a stretched smear on the other - so those draws keep the mono shader whatever the eye is.
// The draw path knows the vertex count and the scissor; it marks each draw here before its pipeline is asked for.
void vk_stereo_screen_pass(int v) { screen_pass = v; }

// A pass whose target is square is a shadow map: MKW renders its cascades as 1024/2048/4096 squares, never 16:9.
// Those passes are the light's view, not the player's, so they must be drawn with the mono shader: shear them and
// each eye gets a shadow map where every caster sits somewhere else, which the eyes read as two opposite lights.
static _Thread_local int pass_w, pass_h, pass_depth = 1;
void vk_stereo_pass(int w, int h, int has_depth) { pass_w = w, pass_h = h, pass_depth = has_depth; }
// A pass with no depth attachment draws into a mask or a post-process target (the game's lighting masks are 480x270 and
// 1920x1080 colour-only). Those are sampled back by screen position, so a shear applied here lands the mask on the wrong
// part of the object and the two eyes disagree: that reads as light coming from two different sides. Keep them mono.
int vk_stereo_pass_square(void) { return pass_w > 0 && (pass_w == pass_h || !pass_depth); }
void vk_stereo_pass_size(int *w, int *h) { *w = pass_w, *h = pass_h; }
int vk_stereo_is_screen_pass(void) { return screen_pass; }

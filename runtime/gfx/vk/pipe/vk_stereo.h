// Stereo 3D state (vk_stereo.c): the eye a submission is recorded for, and the settings that place it.
#ifndef VK_STEREO_H
#define VK_STEREO_H

void vk_stereo_init(void);            // read cfg once; call before any pipeline is built
int vk_stereo_on(void);               // STEREO=1 and a separation that is not 0
float vk_stereo_sep(void);            // STEREO_SEP: the half eye separation, clip units
float vk_stereo_conv(void);           // STEREO_CONV: the w at which the eyes agree
int vk_stereo_eye(void);              // -1 left, +1 right, 0 mono (what make_module writes into the shader)
void vk_stereo_next(void);            // the next submission shows the other eye
int vk_stereo_side_left(void);        // the newest image is the left eye's

#endif
void vk_stereo_screen_pass(int v);
void vk_stereo_pass(int w, int h, int has_depth);
int vk_stereo_pass_square(void);
void vk_stereo_pass_size(int *w, int *h);   // marks the draw about to ask for its pipeline: 1 for a full-screen pass
int vk_stereo_is_screen_pass(void);  // 1 when this draw is a full-screen pass and must stay mono

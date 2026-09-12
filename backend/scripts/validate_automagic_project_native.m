function validate_automagic_project_native(input_path, output_root, source_root, eeglab_root, prep_root, ica_random_policy)
% Independently execute the pinned author's complete Project/Block chain.
% The shared policy accepts autoBadChans for the author's interpolation stage.
assert(~isfolder(output_root),'Use a new validation directory'); mkdir(output_root);
if nargin<6,ica_random_policy='author_clock';end
assert(any(strcmp(ica_random_policy,{'author_clock','fixed_loop_seed_zero'})),'Unknown ICA random policy');
if strcmp(ica_random_policy,'fixed_loop_seed_zero')
    derived=fullfile(output_root,'author-automagic');copyfile(source_root,derived);
    target=fullfile(derived,'preprocessing','performICLabel.m');contents=fileread(target);
    marker='''''chanind'''',EEG.icachansind)';
    assert(numel(strfind(contents,marker))==1,'Pinned ICA call site changed');
    contents=strrep(contents,marker, '''''chanind'''',EEG.icachansind,''''rndreset'''',''''no'''')');
    fid=fopen(target,'w');fwrite(fid,contents,'char');fclose(fid);source_root=derived;
end
profile=fullfile(output_root,'profile');mkdir(profile);setenv('USERPROFILE',profile);
set(0,'DefaultFigureVisible','off');
addpath(eeglab_root);addpath(genpath(fullfile(eeglab_root,'functions')));
addpath(genpath(fullfile(eeglab_root,'plugins','firfilt')));
addpath(genpath(fullfile(prep_root,'PrepPipeline')));addpath(genpath(source_root));
input=load(input_path);EEG=input.EEG;
data_root=fullfile(output_root,'input');mkdir(data_root);
record_root=fullfile(data_root,'record');mkdir(record_root);
result_root=fullfile(output_root,'results');mkdir(result_root);
pop_saveset(EEG,'filename','record.set','filepath',record_root,'savemode','onefile');
defaults=DefaultParameters;system=defaults.EEGSystem;system.powerLineFreq=60;
settings=defaults.Settings;settings.trackAllSteps=1;
params=struct('EEGSystem',system,'Settings',settings);
project=Project('native-record',data_root,result_root,'.set',params,struct());
assert(project.nBlock==1,'Expected exactly one input record');
rng(321,'twister');project.preprocessAll();
project.updateRatingStructures();
assert(numel(project.processedList)==1,'Author preprocessing did not complete');
if project.toBeInterpolatedCount()>0,project.interpolateSelected();end
project.updateRatingStructures();
block=project.blockMap(project.processedList{1});finished=load(block.resultAddress);
output=finished.EEG;native_qc=finished.automagic;
save(fullfile(output_root,'native-output.mat'),'output','native_qc','params','-v7');
assert(all(isfinite(output.data(:))),'Nonfinite author final output');
assert(isequal(output.event,EEG.event),'Author final event inventory changed');
assert(output.srate==EEG.srate && size(output.data,2)==EEG.pnts,'Author final sample grid changed');
receipt=struct('status','executed','native_qc',native_qc,'matlab_version',version, ...
 'output_channels',{ {output.chanlocs.labels} },'output_shape',size(output.data), ...
 'shared_decision_policy','accept_author_autoBadChans_for_native_interpolation', ...
 'ica_random_policy',ica_random_policy, ...
 'interpretation','Author complete Project/Block chain; numerical equivalence and downstream eligibility require separate validation.');
fid=fopen(fullfile(output_root,'native-receipt.json'),'w');fwrite(fid,jsonencode(receipt),'char');fclose(fid);
close all;
end

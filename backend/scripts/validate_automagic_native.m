function validate_automagic_native(input_path, output_root, source_root, eeglab_root, prep_root)
% Complete upstream default pipeline with explicit target system/mains binding.
mkdir(output_root); profile_root=fullfile(output_root,'eeglab-profile'); mkdir(profile_root);
setenv('USERPROFILE',profile_root); set(0,'DefaultFigureVisible','off');
addpath(eeglab_root); addpath(genpath(fullfile(eeglab_root,'functions')));
addpath(genpath(fullfile(prep_root,'PrepPipeline')));
addpath(genpath(fullfile(source_root,'preprocessing')));
input=load(input_path); EEG=input.EEG;
defaults=DefaultParameters;
settings=defaults.Settings; settings.trackAllSteps=1; settings.pathToSteps=fullfile(output_root,'all-stages.mat');
system=defaults.EEGSystem; system.powerLineFreq=60;
params=struct('EEGSystem',system,'Settings',settings);
save(fullfile(output_root,'native-input.mat'),'EEG','params','-v7');
receipt=struct('status','running','matlab_version',version,'toolboxes',ver,'parameters',params);
try
    rng(321,'twister'); output=preprocess(EEG,params);
    save(fullfile(output_root,'native-output.mat'),'output','-v7');
    receipt.native_qc=output.automagic;
    serialized=jsonencode(output.automagic);
    if contains(serialized,'FAILED') || (isfield(output.automagic,'error_msg') && ~isempty(output.automagic.error_msg))
        receipt.status='failed'; receipt.reason='An upstream mandatory stage returned failure; remaining stages do not establish complete execution.';
    else
        receipt.status='executed';
    end
    receipt.output_channels={output.chanlocs.labels}; receipt.output_shape=size(output.data);
    receipt.output_sfreq=output.srate; receipt.output_events=output.event;
catch failure
    receipt.status='failed'; receipt.reason=getReport(failure,'extended','hyperlinks','off');
end
fid=fopen(fullfile(output_root,'native-receipt.json'),'w'); fwrite(fid,jsonencode(receipt),'char'); fclose(fid);
close all;
assert(strcmp(receipt.status,'executed'),'Automagic complete native execution failed; inspect the saved receipt');
end

function validate_prep_native(input_path, output_root, source_root, eeglab_root)
% Execute the entire pinned PREP entrypoint twice on an immutable input copy.
% This checks the IO bridge/repeatability, not independent algorithm validity.
mkdir(output_root);
profile_root = fullfile(output_root, 'eeglab-profile'); mkdir(profile_root);
setenv('USERPROFILE', profile_root);
set(0, 'DefaultFigureVisible', 'off');
addpath(genpath(fullfile(eeglab_root, 'functions')));
addpath(genpath(fullfile(eeglab_root, 'plugins', 'firfilt')));
addpath(genpath(fullfile(source_root, 'PrepPipeline')));
input = load(input_path);
EEG = eeg_emptyset;
EEG.data = input.signal_V * 1e6;
EEG.srate = input.sfreq; EEG.nbchan = size(EEG.data, 1);
EEG.pnts = size(EEG.data, 2); EEG.trials = 1;
EEG.xmin = 0; EEG.xmax = (EEG.pnts - 1) / EEG.srate;
EEG.setname = 'BrainAgent immutable real-record input';
EEG.filename = 'native-input'; EEG.ref = 'unknown';
for i = 1:EEG.nbchan
    EEG.chanlocs(i).labels = strtrim(input.channels{i});
    EEG.chanlocs(i).X = input.positions(i, 2);
    EEG.chanlocs(i).Y = -input.positions(i, 1);
    EEG.chanlocs(i).Z = input.positions(i, 3);
    EEG.chanlocs(i).type = 'EEG';
end
EEG.chanlocs = convertlocs(EEG.chanlocs, 'cart2all');
for i = 1:size(input.events, 1)
    if isfield(input,'event_labels')
        EEG.event(i).type = input.event_labels{i};
    else
        EEG.event(i).type = num2str(input.events(i, 3));
    end
    EEG.event(i).latency = input.events(i, 1) - input.first_sample + 1;
    EEG.event(i).duration = 0;
    if isfield(input,'event_durations_samples')
        EEG.event(i).duration = input.event_durations_samples(i);
    end
end
EEG = eeg_checkset(EEG);
params = input.configuration;
save(fullfile(output_root, 'native-input.mat'), 'EEG', 'params', '-v7');
rng(321, 'twister'); [first, firstTimes] = prepPipeline(EEG, params);
save(fullfile(output_root, 'native-first.mat'), 'first', 'firstTimes', '-v7');
receipt = struct('status', 'failed', 'matlab_version', version, 'toolboxes', ver, ...
    'parameters', params, 'first_status', first.etc.noiseDetection.errors, ...
    'first_times', firstTimes, 'random_seed', 321);
fid = fopen(fullfile(output_root, 'native-receipt.json'), 'w');
fwrite(fid, jsonencode(receipt), 'char'); fclose(fid);
assert(strcmp(first.etc.noiseDetection.errors.status, 'good'), 'PREP returned an unprocessed record');
assert(first.etc.noiseDetection.fullReferenceInfo, 'PREP robust reference did not complete');
rng(321, 'twister'); [second, secondTimes] = prepPipeline(EEG, params);
assert(strcmp(second.etc.noiseDetection.errors.status, 'good'), 'PREP repeat returned an unprocessed record');
assert(isequal(first.event, EEG.event) && isequal(second.event, EEG.event), 'Native event inventory changed');
assert(isequal({first.chanlocs.labels}, {EEG.chanlocs.labels}), 'Native channel inventory changed');
assert(isequal(size(first.data), size(EEG.data)), 'Native sample grid changed');
assert(all(isfinite(first.data(:))), 'Nonfinite native output');
signal_V = double(first.data) * 1e-6;
repeat_signal_V = double(second.data) * 1e-6;
save(fullfile(output_root, 'physical-output.mat'), 'signal_V', 'repeat_signal_V', '-v7');
receipt.status = 'executed';
receipt.max_abs_repeat_difference_V = max(abs(signal_V(:) - repeat_signal_V(:)));
receipt.full_reference_info = first.etc.noiseDetection.fullReferenceInfo;
receipt.expanded_native_configuration = first.etc.noiseDetection;
receipt.second_times = secondTimes;
receipt.physical_unit = 'V'; receipt.native_unit = 'uV';
receipt.interpretation = 'Complete source entrypoint and repeated native IO bridge; not independent algorithm validation or final-agent acceptance.';
fid = fopen(fullfile(output_root, 'native-receipt.json'), 'w');
fwrite(fid, jsonencode(receipt), 'char'); fclose(fid);
end

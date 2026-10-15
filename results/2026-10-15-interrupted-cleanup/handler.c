static void handle_failed_reshape(struct r5conf *conf, struct stripe_head *sh,
				  struct stripe_head_state *s)
{
	int i;
	bool was_expanding = test_and_clear_bit(STRIPE_EXPANDING, &sh->state);
	bool was_ready = test_and_clear_bit(STRIPE_EXPAND_READY, &sh->state);

	/* Freeze reshaping to prevent data loss */
	set_bit(MD_RECOVERY_FROZEN, &conf->mddev->recovery);
	md_sync_error(conf->mddev);

	if (was_expanding || was_ready) {
		atomic_dec(&conf->reshape_stripes);
		wake_up(&conf->wait_for_reshape);
		md_done_sync(conf->mddev, RAID5_STRIPE_SECTORS(conf));
	}

	s->expanded = 0;
	s->expanding = 0;

	/* release the destination stripes that are waiting to be filled */
	if (test_and_clear_bit(STRIPE_EXPAND_SOURCE, &sh->state)) {
		for (i = 0; i < sh->disks; i++) {
			int dd_idx;
			struct stripe_head *sh2;
			sector_t bn, sec;

			if (i == sh->pd_idx)
				continue;
			if (conf->level == 6 && i == sh->qd_idx)
				continue;

			bn = raid5_compute_blocknr(sh, i, 1);
			sec = raid5_compute_sector(conf, bn, 0, &dd_idx, NULL);
			sh2 = raid5_get_active_stripe(conf, NULL, sec,
						      R5_GAS_NOBLOCK |
						      R5_GAS_NOQUIESCE);
			if (!sh2)
				continue;

			if (test_and_clear_bit(STRIPE_EXPANDING, &sh2->state)) {
				atomic_dec(&conf->reshape_stripes);
				wake_up(&conf->wait_for_reshape);
				md_done_sync(conf->mddev,
					     RAID5_STRIPE_SECTORS(conf));
			}

			clear_bit(STRIPE_EXPAND_READY, &sh2->state);

			raid5_release_stripe(sh2);
		}
	}
}

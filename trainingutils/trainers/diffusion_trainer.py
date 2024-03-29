from trainingutils.trainers.trainer import Trainer
from trainingutils.utils import Config
from trainingutils.checkpointing import TrainingCheckpointer
from diffusers import DDPMScheduler
from torch.utils.data import DataLoader
import torch
from torch.nn.functional import mse_loss
import tqdm

class DiffusionTrainer(Trainer):
    def __init__(
            self,
            model,
            optim,
            dataset,
            scheduler,
            lr_scheduler,
            device,
            training_config: Config
        ):
        super().__init__(
            model,
            optim,
            dataset,
            device,
            training_config
        )

        self.scheduler: DDPMScheduler = scheduler
        self.learning_rate_scheduler = lr_scheduler

    @classmethod
    def get_default_config(self) -> Config:
        # Default Diffusion parameters
        max_timesteps: int = 1000

        # Default checkpointing parameters
        checkpoint: bool = True
        checkpoint_path: str = "./checkpoints/"
        checkpoint_iter: int = 50

        # Default training parameters
        learning_rate: float = 1e-4
        learning_rate_warmup_steps: int = 500
        epochs: int = 1000
        batch_size: int = 5
        shuffle: bool = True

        # Acceleration Parameters
        mixed_precision = "fp16"
        gradient_accum_steps=1
        output_dir="ddpm-craters"
        
        return Config(
            max_timesteps=max_timesteps,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            checkpoint_iter=checkpoint_iter,
            learning_rate=learning_rate,
            learning_rate_warmup_steps=learning_rate_warmup_steps,
            epochs=epochs,
            batch_size=batch_size,
            shuffle=shuffle,
            mixed_precision=mixed_precision,
            gradient_accum_steps=gradient_accum_steps,
            output_dir=output_dir
        )

    def train(self) -> None:
        dataloader = DataLoader(
            self.dataset,
            batch_size=self.batch_size,
            shuffle=self.shuffle,
            drop_last=True
        )

        losses = []

        for epoch in tqdm.tqdm(range(self.epoch_iter, self.epochs), desc="Epoch"):
            self.epoch_iter = epoch
            
            loss_sum = 0
            for data in tqdm.tqdm(dataloader, desc="Batch", leave=False):
                # Zero the gradients
                self.optimizer.zero_grad()
                
                # Unpack data and put it on the GPU
                image, b, r = data
                b = b.to(self.device).long()
                r = r.to(self.device).float().view(r.size()[0], 1)

                # Add t-timesteps of noise to the image
                dims = image.size()
                noise = torch.randn(dims)
                timesteps = torch.randint(1000, (dims[0],), dtype=torch.int64)
                noisey_batch = self.scheduler.add_noise(image, noise, timesteps)

                # Put the noisy image and timesteps on the GPU
                noisey_batch = noisey_batch.to(self.device)
                noise = noise.to(self.device)
                timesteps = timesteps.to(self.device)

                # Predict the noise with the model
                predicted_noise = self.model(
                    x=noisey_batch,
                    timestep=timesteps,
                    body=b,
                    radius=r
                )

                # Calculate the loss and backpropagate
                loss = mse_loss(noise, predicted_noise)
                loss.backward()

                # Step the optimizer and learning rate scheduler
                self.optimizer.step()
                self.learning_rate_scheduler.step()

                # Sum the loss for the epoch
                loss_sum += loss.item()
            
            losses.append(loss_sum / len(dataloader))
            if epoch % self.checkpoint_iter == 0 and self.checkpoint and bool(epoch):
                self._save(epoch, losses)
